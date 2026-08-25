"""Collector for Indexer, Oracle, and Analytics changelogs (L2BEAT, Goldsky, SQD, Dune)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.config import settings
from src.core.normalizer import extract_effective_domain, format_caip2, normalize_chain_id
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
from src.verifier.safe_url import safe_http_client


class IndexerChangelogCollector:
    source_id: str = "indexer_changelogs"
    family: str = "infrastructure"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=20, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        # Example fetching Goldsky or L2BEAT scaling summary
        url = "https://api.l2beat.com/api/scaling/summary"
        headers = {"User-Agent": "AshinityEarlyChainDiscovery/1.0"}
        items: List[RawItem] = []

        try:
            resp = await safe_http_client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                projects = data.get("data", {}).get("projects", {})
                for p_id, p_val in projects.items():
                    name = p_val.get("name", p_id)
                    stage = p_val.get("stage")
                    content_str = json.dumps(p_val, sort_keys=True)
                    c_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

                    items.append(
                        RawItem(
                            source_id=self.source_id,
                            external_id=f"l2beat_{p_id}",
                            url=f"https://l2beat.com/scaling/projects/{p_id}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            raw_payload=p_val,
                            content_hash=c_hash,
                            provenance={"source": "l2beat", "project_id": p_id},
                        )
                    )
        except Exception:
            pass

        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=Cursor(source_id=self.source_id, last_seen_timestamp=datetime.now(timezone.utc)),
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        name = payload.get("name", "Unknown Scaling Project")
        slug = payload.get("slug")
        chain_type = payload.get("type", "layer2")
        provider = payload.get("provider") # e.g. OP Stack, Arbitrum, ZK Stack

        stack_family = StackFamily.EVM
        if provider:
            prov_lower = provider.lower()
            if "stark" in prov_lower:
                stack_family = StackFamily.STARKNET
            elif "cosmos" in prov_lower:
                stack_family = StackFamily.COSMOS

        obs = RawObservation(
            candidate_name=name,
            candidate_slug=slug,
            stack_family=stack_family,
            stack_details=provider,
            layer="L2" if chain_type == "layer2" else "L3",
            environment=NetworkEnvironment.MAINNET,
            is_public=True,
            stage=LifecycleStage.S5_EARLY_MAINNET,
            raw_text=json.dumps(payload),
            claims={"l2beat_provider": provider, "category": payload.get("category")},
            reliability=0.90,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
