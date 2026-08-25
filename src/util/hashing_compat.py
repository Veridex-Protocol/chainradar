"""Deterministic hashing of JSON-able payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_payload_hash(payload: Any) -> str:
    """SHA-256 over a canonical JSON rendering (key order normalized)."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
