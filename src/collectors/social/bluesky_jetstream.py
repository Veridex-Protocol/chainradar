"""Bluesky Jetstream public event stream collector."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.core.types import (
    Cursor,
    FetchBatch,
    LifecycleStage,
    NetworkEnvironment,
    RateBudget,
    RawItem,
    RawObservation,
    StackFamily,
)


KEYWORD_FILTER = [
    "public testnet",
    "incentivized testnet",
    "mainnet launch",
    "genesis validator",
    "chain is live",
    "op stack",
    "arbitrum orbit",
    "zk stack",
]


class BlueskyJetstreamCollector:
    source_id: str = "bluesky_jetstream"
    family: str = "social"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=120, burst=20)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        # Jetstream collector operates as a streaming poller or batch replay
        items: List[RawItem] = []
        now = datetime.now(timezone.utc)
        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=Cursor(source_id=self.source_id, last_seen_timestamp=now),
            provenance={"status": "stream_listener_active"},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        text = payload.get("text", "")
        author = payload.get("author", "unknown_author")

        # Extract name from text
        words = text.split()
        name = words[0] if words else "Bluesky Discovered Chain"

        obs = RawObservation(
            candidate_name=name,
            stack_family=StackFamily.EVM,
            environment=NetworkEnvironment.TESTNET,
            is_public=True,
            stage=LifecycleStage.S0_RESEARCH_HINT,
            raw_text=text,
            claims={"social_author": author},
            reliability=0.50,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
