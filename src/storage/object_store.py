"""Object store for compressed, immutable raw evidence payloads."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Tuple
from src.config import settings


class ObjectStore:
    """Content-addressable compressed storage for raw collector responses and payloads."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir or settings.OBJECT_STORE_PATH).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _compute_hash(self, content_bytes: bytes) -> str:
        return hashlib.sha256(content_bytes).hexdigest()

    def store_payload(self, source_id: str, raw_data: Any) -> Tuple[str, str]:
        """Compresses and stores raw payload on disk.
        
        Returns:
            Tuple[content_hash, relative_path]
        """
        if isinstance(raw_data, (dict, list)):
            data_bytes = json.dumps(raw_data, sort_keys=True, default=str).encode("utf-8")
        elif isinstance(raw_data, str):
            data_bytes = raw_data.encode("utf-8")
        elif isinstance(raw_data, bytes):
            data_bytes = raw_data
        else:
            data_bytes = str(raw_data).encode("utf-8")

        content_hash = self._compute_hash(data_bytes)
        
        # Structure by source_id and first 2 characters of hash for efficient folder scaling
        sub_dir = self.base_dir / source_id / content_hash[:2]
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = sub_dir / f"{content_hash}.json.gz"
        compressed_bytes = gzip.compress(data_bytes)
        
        with open(file_path, "wb") as f:
            f.write(compressed_bytes)

        relative_path = str(file_path.relative_to(self.base_dir))
        return content_hash, relative_path

    def retrieve_payload(self, relative_path: str) -> Optional[Any]:
        """Retrieves and decompresses raw payload from disk."""
        file_path = self.base_dir / relative_path
        if not file_path.exists():
            return None

        with open(file_path, "rb") as f:
            compressed_bytes = f.read()

        decompressed = gzip.decompress(compressed_bytes)
        try:
            return json.loads(decompressed.decode("utf-8"))
        except Exception:
            try:
                return decompressed.decode("utf-8")
            except Exception:
                return decompressed


object_store = ObjectStore()
