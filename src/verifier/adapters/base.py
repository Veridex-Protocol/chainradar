"""Base protocol adapter interface."""

from __future__ import annotations

from typing import Optional, Protocol
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity


class ProtocolAdapter(Protocol):
    """Protocol adapter for querying blockchain node identity and liveness."""
    family: str

    async def identity(self, endpoint: str) -> NetworkIdentity:
        """Fetches chain identity, namespace, chain ID, and client/spec versions."""
        ...

    async def head(self, endpoint: str) -> HeadObservation:
        """Fetches latest block/checkpoint height and timestamp."""
        ...

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        """Fetches genesis hash / block 0 hash if supported."""
        ...
