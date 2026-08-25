"""Base collector interface and rate budgeting."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from src.core.types import Cursor, FetchBatch, RateBudget, RawItem, RawObservation


@runtime_checkable
class Collector(Protocol):
    """Protocol for all data source collectors in the intelligence engine."""
    source_id: str
    family: str
    tier: str

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        """Fetches a batch of raw items from the external source using cursor."""
        ...

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        """Converts raw source item into one or more standardized candidate observations."""
        ...

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        """Advances the cursor safely based on successfully fetched batch."""
        ...


class TokenBucketLimiter:
    """Per-source in-memory token bucket rate limiter with jitter support."""

    def __init__(self, requests_per_minute: int = 60, burst: int = 10):
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.fill_rate = requests_per_minute / 60.0
        self.last_update = datetime.now(timezone.utc).timestamp()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        async with self.lock:
            now = datetime.now(timezone.utc).timestamp()
            delta = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + delta * self.fill_rate)
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
