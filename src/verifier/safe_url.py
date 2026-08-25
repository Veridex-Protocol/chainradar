"""SSRF-hardened URL validation and read-only HTTP client (spec 15).

Untrusted RPC URLs are attacker-controlled input. Three properties matter and
each is enforced here rather than left to the caller:

1. *Every* address a hostname resolves to must be a public unicast address.
   Checking only the first answer lets a round-robin record smuggle a private
   target through.

2. The connection is pinned to an address that was actually validated. Naive
   guards validate a URL and then hand that URL to an HTTP client, which
   resolves the name a second time - a DNS rebinding window (spec 15 requires
   binding verification to the validated resolution). We substitute the
   validated IP into the request URL and carry the real hostname in the Host
   header and in the TLS `sni_hostname` extension, which drives both SNI and
   certificate verification, so pinning costs nothing in TLS strength.

3. Response bodies are capped while streaming, so an oversized or malicious
   body is aborted at the cap instead of being buffered first.

The client is read-only by construction: it exposes GET and a JSON POST used
for JSON-RPC reads, sends no cookies or credentials, and never follows a
redirect unless policy explicitly allows it (each hop is re-validated).
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from src.config import settings

# Networks that must never be reached, beyond what `is_global` already covers.
# Listed explicitly so the intent is auditable during a security review.
_EXPLICIT_DENY = [
    ipaddress.ip_network("0.0.0.0/8"),        # "this network"
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("169.254.0.0/16"),   # link-local + cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918
    ipaddress.ip_network("192.0.0.0/24"),     # IETF protocol assignments
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918
    ipaddress.ip_network("198.18.0.0/15"),    # benchmarking
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),           # unspecified
    ipaddress.ip_network("::1/128"),          # loopback
    ipaddress.ip_network("fc00::/7"),         # unique local
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("ff00::/8"),         # multicast
    ipaddress.ip_network("2001:db8::/32"),    # documentation
]

# Well-known cloud instance-metadata endpoints (spec 15: metadata-service).
_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),  # AWS / GCP / Azure / DO
    ipaddress.ip_address("169.254.170.2"),    # AWS ECS task metadata
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
    ipaddress.ip_address("fd00:ec2::254"),    # AWS IMDSv6
}

# IPv6 transition ranges that embed an IPv4 address. An attacker can wrap a
# private IPv4 target in one of these to slip past an IPv4-only blocklist, so
# the embedded address is extracted and validated on its own.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIXTOFOUR = ipaddress.ip_network("2002::/16")


class SSRFValidationError(ValueError):
    """Raised when an endpoint URL violates SSRF safety controls."""


@dataclass(frozen=True)
class ValidatedTarget:
    """A URL proven safe, together with the address the request must use."""

    original_url: str
    scheme: str
    hostname: str
    port: int
    ip: str
    all_ips: Tuple[str, ...]

    @property
    def pinned_url(self) -> str:
        """The original URL with the validated IP substituted for the host."""
        parts = urlsplit(self.original_url)
        literal = f"[{self.ip}]" if ":" in self.ip else self.ip
        return urlunsplit((parts.scheme, f"{literal}:{self.port}", parts.path or "/", parts.query, ""))

    @property
    def host_header(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        return self.hostname if self.port == default_port else f"{self.hostname}:{self.port}"


def _unwrap_embedded_ipv4(ip: ipaddress._BaseAddress) -> List[ipaddress._BaseAddress]:
    """Return the address plus any IPv4 address embedded inside it."""
    found: List[ipaddress._BaseAddress] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            found.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            found.append(ip.sixtofour)
        if getattr(ip, "teredo", None):
            found.extend(a for a in ip.teredo if a is not None)
        if ip in _NAT64:
            # Low 32 bits of a NAT64 address are the embedded IPv4 address.
            found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip in _SIXTOFOUR:
            found.append(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
    return found


def is_ip_blocked(ip_str: str) -> bool:
    """True when an address must not be contacted.

    Fails closed: anything unparseable is treated as blocked.
    """
    try:
        parsed = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    for candidate in _unwrap_embedded_ipv4(parsed):
        if candidate in _METADATA_ADDRESSES:
            return True
        if any(candidate in net for net in _EXPLICIT_DENY if net.version == candidate.version):
            return True
        # Catch-all for reserved space the explicit list may not enumerate.
        if (
            candidate.is_loopback
            or candidate.is_private
            or candidate.is_link_local
            or candidate.is_multicast
            or candidate.is_reserved
            or candidate.is_unspecified
        ):
            return True
    return False


class SafeURLValidator:
    """Validates URLs against scheme, port and address-space policy."""

    @staticmethod
    def is_ip_blocked(ip_str: str) -> bool:
        return is_ip_blocked(ip_str)

    @classmethod
    def resolve_and_validate(cls, url: str) -> ValidatedTarget:
        """Validate a URL and resolve it to a pinned, safe address.

        Raises:
            SSRFValidationError: on any scheme, port, DNS or address violation.
        """
        if not url or not isinstance(url, str):
            raise SSRFValidationError("URL is empty.")

        cfg = settings.VERIFY
        try:
            parsed = urlsplit(url.strip())
        except ValueError as exc:
            raise SSRFValidationError(f"Unparseable URL: {exc}") from exc

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise SSRFValidationError(
                f"Disallowed scheme '{scheme}'. Only http/https are permitted for HTTP collectors."
            )

        try:
            hostname = parsed.hostname
        except ValueError as exc:
            raise SSRFValidationError(f"Invalid host in URL: {exc}") from exc
        if not hostname:
            raise SSRFValidationError(f"Invalid host in URL: {url}")

        allowed_schemes = {s.lower() for s in cfg.allowed_schemes}
        if scheme not in allowed_schemes:
            # http is permitted only for hosts on the explicit policy list.
            if not (scheme == "http" and hostname.lower() in {h.lower() for h in cfg.allow_http_hosts}):
                raise SSRFValidationError(
                    f"Scheme '{scheme}' is not permitted for host '{hostname}' by policy."
                )

        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise SSRFValidationError(f"Invalid port in URL: {exc}") from exc
        if port not in set(cfg.allowed_ports):
            raise SSRFValidationError(f"Disallowed port '{port}'.")

        # A bare IP literal skips DNS but must still satisfy address policy.
        try:
            literal = ipaddress.ip_address(hostname.strip("[]"))
        except ValueError:
            literal = None

        if literal is not None:
            if is_ip_blocked(str(literal)):
                raise SSRFValidationError(f"Host '{hostname}' is a prohibited address '{literal}'.")
            return ValidatedTarget(url, scheme, hostname, port, str(literal), (str(literal),))

        try:
            addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except OSError as exc:
            raise SSRFValidationError(f"DNS resolution failed for '{hostname}': {exc}") from exc

        resolved = sorted({info[4][0] for info in addr_info})
        if not resolved:
            raise SSRFValidationError(f"No IP addresses resolved for '{hostname}'.")

        # Every answer must be safe. Validating only the chosen address would
        # let a multi-answer record rotate a private target into place.
        for ip in resolved:
            if is_ip_blocked(ip):
                raise SSRFValidationError(f"Host '{hostname}' resolved to prohibited IP '{ip}'.")

        return ValidatedTarget(url, scheme, hostname, port, resolved[0], tuple(resolved))

    @classmethod
    def validate_url(cls, url: str) -> Tuple[str, str, int]:
        """Backwards-compatible wrapper returning ``(scheme, ip, port)``."""
        target = cls.resolve_and_validate(url)
        return target.scheme, target.ip, target.port


class _DomainLimiter:
    """Per-domain token bucket plus a concurrency cap (spec 15 'Rate')."""

    def __init__(self, rate_per_minute: int, concurrency: int) -> None:
        self.capacity = max(1, rate_per_minute)
        self.tokens = float(self.capacity)
        self.refill_per_second = self.capacity / 60.0
        self.updated_at = time.monotonic()
        self.semaphore = asyncio.Semaphore(max(1, concurrency))
        # Set when a 429/503 asks us to back off until a point in time.
        self.retry_after_until = 0.0

    async def acquire(self, jitter_seconds: float) -> None:
        now = time.monotonic()
        if now < self.retry_after_until:
            await asyncio.sleep(self.retry_after_until - now)
        while True:
            now = time.monotonic()
            self.tokens = min(
                float(self.capacity),
                self.tokens + (now - self.updated_at) * self.refill_per_second,
            )
            self.updated_at = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                break
            await asyncio.sleep(max(0.05, (1.0 - self.tokens) / self.refill_per_second))
        if jitter_seconds > 0:
            # Desynchronize collectors that would otherwise fire together.
            await asyncio.sleep(random.uniform(0, jitter_seconds))

    def note_retry_after(self, seconds: float) -> None:
        self.retry_after_until = max(self.retry_after_until, time.monotonic() + seconds)


class ResponseTooLarge(ValueError):
    """Raised when a response body exceeds the configured cap."""


class SafeHttpClient:
    """Read-only HTTP client enforcing SSRF, rate, timeout and size policy."""

    def __init__(
        self,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        max_response_bytes: Optional[int] = None,
        max_redirects: Optional[int] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        cfg = settings.VERIFY
        self.connect_timeout = connect_timeout if connect_timeout is not None else cfg.connect_timeout_seconds
        self.read_timeout = read_timeout if read_timeout is not None else cfg.read_timeout_seconds
        self.max_response_bytes = (
            max_response_bytes if max_response_bytes is not None else cfg.max_response_bytes
        )
        self.max_redirects = max_redirects if max_redirects is not None else cfg.max_redirects
        self._limiters: Dict[str, _DomainLimiter] = {}
        # Injectable for tests. Validation, pinning and caps still apply, so a
        # test transport exercises policy rather than bypassing it.
        self._transport = transport

    # -- internals ---------------------------------------------------------
    def _limiter(self, hostname: str) -> _DomainLimiter:
        cfg = settings.VERIFY
        if hostname not in self._limiters:
            self._limiters[hostname] = _DomainLimiter(
                cfg.per_domain_rate_per_minute, cfg.per_domain_concurrency
            )
        return self._limiters[hostname]

    @property
    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.read_timeout,
            pool=self.connect_timeout,
        )

    async def _read_capped(self, response: httpx.Response) -> bytes:
        """Stream a body, aborting as soon as the cap is exceeded."""
        chunks: List[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_response_bytes:
                await response.aclose()
                raise ResponseTooLarge(
                    f"Response exceeded {self.max_response_bytes} byte cap (read {total})."
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        json_payload: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        _redirects_left: Optional[int] = None,
    ) -> httpx.Response:
        # Re-validate and re-resolve immediately before every connection, and
        # again for each redirect hop (spec 15 'Re-check').
        target = SafeURLValidator.resolve_and_validate(url)
        redirects_left = self.max_redirects if _redirects_left is None else _redirects_left

        request_headers: Dict[str, str] = {
            "Host": target.host_header,
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "AshinityECD/1.0 (+market-intelligence; read-only)",
        }
        if headers:
            request_headers.update(headers)
        if json_payload is not None:
            request_headers.setdefault("Content-Type", "application/json")

        limiter = self._limiter(target.hostname)
        await limiter.acquire(settings.VERIFY.jitter_seconds)

        async with limiter.semaphore:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,   # every hop is validated by hand
                trust_env=False,          # ignore proxy env vars on this path
                cookies=None,             # never carry cookies or credentials
                transport=self._transport,
            ) as client:
                request = client.build_request(
                    method,
                    target.pinned_url,
                    json=json_payload,
                    headers=request_headers,
                    # Drives SNI *and* certificate verification, so pinning to
                    # an IP keeps full hostname verification against the cert.
                    extensions={"sni_hostname": target.hostname},
                )
                response = await client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        await response.aclose()
                        if redirects_left <= 0 or not location:
                            raise SSRFValidationError(
                                f"Redirect not permitted by policy (max_redirects={self.max_redirects})."
                            )
                        next_url = httpx.URL(target.original_url).join(location)
                        return await self._send(
                            method,
                            str(next_url),
                            json_payload=json_payload,
                            headers=headers,
                            _redirects_left=redirects_left - 1,
                        )

                    if response.status_code in (429, 503):
                        retry_after = response.headers.get("retry-after")
                        if retry_after:
                            try:
                                limiter.note_retry_after(min(300.0, float(retry_after)))
                            except ValueError:
                                limiter.note_retry_after(60.0)
                        else:
                            limiter.note_retry_after(30.0)

                    body = await self._read_capped(response)
                finally:
                    if not response.is_closed:
                        await response.aclose()

        # Rebuild a fully-read response so callers can use .json()/.text.
        # `aiter_bytes()` already applied content decoding, so the framing
        # headers must be dropped or httpx would decode the body a second time.
        replay_headers = [
            (k, v)
            for k, v in response.headers.multi_items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        ]
        replay_headers.append(("content-length", str(len(body))))
        return httpx.Response(
            status_code=response.status_code,
            headers=replay_headers,
            content=body,
            request=request,
        )

    # -- public API --------------------------------------------------------
    async def get(self, url: str, headers: Optional[dict] = None) -> httpx.Response:
        return await self._send("GET", url, headers=headers)

    async def post_json(
        self, url: str, json_payload: dict, headers: Optional[dict] = None
    ) -> httpx.Response:
        return await self._send("POST", url, json_payload=json_payload, headers=headers)


safe_http_client = SafeHttpClient()
