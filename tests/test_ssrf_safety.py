"""SSRF penetration and network-control tests (spec 15, acceptance test 8).

Covers the four fixture classes the spec names explicitly - localhost, private
IPv4/IPv6, metadata IP, redirect-to-private and DNS rebinding - plus the
address-encoding tricks that defeat a naive IPv4-only blocklist.
"""

import ipaddress
import socket

import httpx
import pytest

from src.verifier.safe_url import (
    ResponseTooLarge,
    SafeHttpClient,
    SafeURLValidator,
    SSRFValidationError,
    is_ip_blocked,
)


def test_ssrf_blocks_private_ipv4():
    blocked = [
        "http://127.0.0.1:8545",
        "http://127.0.1.1:8545",
        "http://10.0.0.1:8545",
        "http://10.254.254.254:8545",
        "http://172.16.0.1:8545",
        "http://172.31.255.255:8545",
        "http://192.168.0.1:8545",
        "http://192.168.100.200:8545",
        "http://0.0.0.0:8545",
        "http://100.64.0.1:8545",          # carrier-grade NAT
        "http://198.18.0.1:8545",          # benchmarking range
    ]
    for url in blocked:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_cloud_metadata_ip():
    metadata_urls = [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://169.254.170.2/v2/credentials",   # AWS ECS task metadata
        "http://100.100.100.200/latest/meta-data/",  # Alibaba Cloud
        "http://169.254.1.1:8080",
    ]
    for url in metadata_urls:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_ipv6_special_ranges():
    ipv6_blocked = [
        "http://[::1]:8545",
        "http://[fe80::1]:8545",
        "http://[fc00::1]:8545",
        "http://[ff02::1]:8545",
        "http://[::]:8545",
        "http://[2001:db8::1]:8545",   # documentation range
    ]
    for url in ipv6_blocked:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_blocks_ipv4_embedded_in_ipv6():
    """IPv4-mapped, NAT64 and 6to4 addresses must not smuggle private targets.

    These parse as IPv6 and therefore match none of the IPv4 private networks;
    an IPv4-only blocklist lets `::ffff:169.254.169.254` reach the metadata
    service. The embedded address has to be extracted and judged on its own.
    """
    assert is_ip_blocked("::ffff:169.254.169.254")   # metadata via IPv4-mapped
    assert is_ip_blocked("::ffff:127.0.0.1")         # loopback via IPv4-mapped
    assert is_ip_blocked("::ffff:10.0.0.5")          # RFC1918 via IPv4-mapped
    assert is_ip_blocked("::ffff:192.168.1.1")
    assert is_ip_blocked("64:ff9b::7f00:1")          # NAT64 -> 127.0.0.1
    assert is_ip_blocked("64:ff9b::a9fe:a9fe")       # NAT64 -> 169.254.169.254
    assert is_ip_blocked("2002:a9fe:a9fe::1")        # 6to4 -> 169.254.169.254

    for url in ["http://[::ffff:169.254.169.254]:80", "http://[::ffff:127.0.0.1]:8545"]:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_ssrf_allows_public_unicast():
    for ip in ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "2001:4860:4860::8888"]:
        assert not is_ip_blocked(ip)


def test_ssrf_fails_closed_on_unparseable_address():
    for junk in ["", "not-an-ip", "0177.0.0.1", "999.999.999.999", "::ffff:junk"]:
        assert is_ip_blocked(junk)


def test_ssrf_blocks_unauthorized_schemes_and_ports():
    for url in [
        "ftp://public.node.com/rpc",
        "file:///etc/passwd",
        "gopher://public.node.com",
        "ws://public.node.com",
        "wss://public.node.com",
    ]:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)

    for url in ["http://1.1.1.1:22", "http://1.1.1.1:25", "http://1.1.1.1:6379", "http://1.1.1.1:5432"]:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


def test_every_resolved_address_must_be_safe(monkeypatch):
    """A record mixing a public and a private answer must be rejected.

    Validating only the first answer would let a round-robin record rotate a
    private target into place between validation and connection.
    """
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(SSRFValidationError, match="169.254.169.254"):
        SafeURLValidator.validate_url("https://rebind.example/rpc")


def test_dns_rebinding_is_rechecked_before_every_connection(monkeypatch):
    """Resolution is re-validated per connection, not cached from a first pass.

    A rebinding attacker answers public on the validation lookup and private on
    the connect lookup. The guard must re-resolve and refuse the second time.
    """
    calls = {"n": 0}

    def flipping_getaddrinfo(host, port, *args, **kwargs):
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", flipping_getaddrinfo)

    first = SafeURLValidator.resolve_and_validate("https://rebind.example/rpc")
    assert first.ip == "93.184.216.34"
    # The pinned address is carried on the target, so the request cannot drift
    # to whatever DNS returns next.
    assert "93.184.216.34" in first.pinned_url and "rebind.example" not in first.pinned_url

    with pytest.raises(SSRFValidationError, match="127.0.0.1"):
        SafeURLValidator.resolve_and_validate("https://rebind.example/rpc")


@pytest.mark.asyncio
async def test_redirect_to_private_is_refused(monkeypatch):
    """A 302 pointing at the metadata service must never be followed."""
    def public_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    client = SafeHttpClient(transport=httpx.MockTransport(handler), max_redirects=0)
    with pytest.raises(SSRFValidationError):
        await client.get("https://public.example/rpc")

    # Even with redirects allowed by policy, the private hop is still rejected.
    client_allow = SafeHttpClient(transport=httpx.MockTransport(handler), max_redirects=3)
    with pytest.raises(SSRFValidationError):
        await client_allow.get("https://public.example/rpc")


@pytest.mark.asyncio
async def test_oversized_body_aborts_at_cap(monkeypatch):
    """The cap aborts the stream instead of buffering the whole body first."""
    def public_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"A" * 50_000)

    client = SafeHttpClient(transport=httpx.MockTransport(handler), max_response_bytes=1024)
    with pytest.raises(ResponseTooLarge):
        await client.get("https://public.example/big")


@pytest.mark.asyncio
async def test_retry_after_is_recorded_without_data_loss(monkeypatch):
    """A 429 is surfaced to the caller and arms per-domain backoff (spec 15)."""
    def public_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "30"}, json={"error": "slow down"})

    client = SafeHttpClient(transport=httpx.MockTransport(handler))
    response = await client.get("https://public.example/rpc")
    assert response.status_code == 429
    assert response.json()["error"] == "slow down"
    limiter = client._limiter("public.example")
    assert limiter.retry_after_until > 0, "Retry-After must arm per-domain backoff"


@pytest.mark.asyncio
async def test_request_is_pinned_and_carries_real_host(monkeypatch):
    """The connection targets the validated IP while TLS/Host see the name."""
    seen = {}

    def public_dns(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, json={"ok": True})

    client = SafeHttpClient(transport=httpx.MockTransport(handler))
    response = await client.get("https://public.example/rpc")

    assert response.json() == {"ok": True}
    assert seen["url"].startswith("https://93.184.216.34/"), "must connect to the validated IP"
    assert seen["host"] == "public.example", "Host header must carry the real name"
    assert seen["sni"] == "public.example", "TLS verification must target the real name"
