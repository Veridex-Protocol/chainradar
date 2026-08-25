"""Secret redaction for logs and evidence payloads (spec 15).

Provider API keys routinely live inside RPC URLs, either as a query parameter
or as a path segment (``/v2/<key>``). Neither may reach a log line, an evidence
payload or an analyst-facing evidence card.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

_SECRET_PARAM_TOKENS = ("key", "token", "secret", "auth", "apikey", "password", "sig")
# Long opaque path segments with no dot are almost always provider keys.
_KEYLIKE_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{24,}$")


def redact_url(url: str) -> str:
    """Return a URL safe to log or store, with credentials removed."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable-url>"

    netloc = parts.netloc
    if "@" in netloc:
        netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]

    query = ""
    if parts.query:
        pairs = []
        for chunk in parts.query.split("&"):
            key, sep, _value = chunk.partition("=")
            if sep and any(tok in key.lower() for tok in _SECRET_PARAM_TOKENS):
                pairs.append(f"{key}=<redacted>")
            else:
                pairs.append(chunk)
        query = "&".join(pairs)

    segments = parts.path.split("/")
    redacted_segments = [
        "<redacted>" if _KEYLIKE_SEGMENT.match(seg) else seg for seg in segments
    ]
    path = "/".join(redacted_segments)

    return urlunsplit((parts.scheme, netloc, path, query, parts.fragment))


def endpoint_hash(url: str) -> str:
    """Stable identifier for an endpoint that never exposes its secret."""
    return hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()


def channel_hash(value: str) -> str:
    """Normalized hash of a contact channel, used for suppression matching."""
    return hashlib.sha256((value or "").strip().casefold().encode("utf-8")).hexdigest()
