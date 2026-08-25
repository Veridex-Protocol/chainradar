"""Normalization utilities for names, domains, and blockchain identifiers."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse
from typing import Any, Optional


LEGAL_SUFFIXES = [
    r"\blabs\b",
    r"\bfoundation\b",
    r"\bnetwork\b",
    r"\bprotocol\b",
    r"\btechnologies\b",
    r"\btechnology\b",
    r"\btech\b",
    r"\bllc\b",
    r"\binc\b",
    r"\bltd\b",
    r"\bgmbh\b",
    r"\bdao\b",
    r"\bventures\b",
    r"\bgroup\b",
    r"\bchain\b",
]

PUNCTUATION_REGEX = re.compile(r"[^\w\s-]")
WHITESPACE_REGEX = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalizes an entity name with Unicode NFKC, lowercasing, and whitespace collapse."""
    if not name:
        return ""
    # Unicode NFKC
    nfkc = unicodedata.normalize("NFKC", name).lower().strip()
    # Collapse punctuation
    cleaned = PUNCTUATION_REGEX.sub(" ", nfkc)
    # Collapse whitespace
    collapsed = WHITESPACE_REGEX.sub(" ", cleaned).strip()
    return collapsed


def strip_legal_suffixes(name: str) -> str:
    """Strips common corporate/legal suffixes to get the core root identity."""
    norm = normalize_name(name)
    for suffix_pat in LEGAL_SUFFIXES:
        norm = re.sub(suffix_pat, "", norm, flags=re.IGNORECASE).strip()
    norm = WHITESPACE_REGEX.sub(" ", norm).strip()
    return norm


def slugify(text: str) -> str:
    """Generates a clean URL/identifier slug."""
    norm = normalize_name(text)
    slug = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return slug or "unknown"


def extract_effective_domain(url: str) -> Optional[str]:
    """Extracts normalized hostname/effective domain from a URL."""
    if not url:
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return None
        hostname = hostname.lower().strip()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return None


def normalize_chain_id(chain_id_val: Any) -> Optional[str]:
    """Normalizes decimal or hex chain IDs into canonical decimal string representation."""
    if chain_id_val is None:
        return None
    if isinstance(chain_id_val, int):
        return str(chain_id_val)
    val_str = str(chain_id_val).strip()
    if val_str.startswith("0x") or val_str.startswith("0X"):
        try:
            return str(int(val_str, 16))
        except ValueError:
            return val_str
    try:
        return str(int(val_str))
    except ValueError:
        return val_str


def format_caip2(namespace: str, reference: str) -> str:
    """Formats CAIP-2 identifier: namespace:reference."""
    clean_ns = namespace.lower().strip()
    clean_ref = str(reference).strip()
    return f"{clean_ns}:{clean_ref}"
