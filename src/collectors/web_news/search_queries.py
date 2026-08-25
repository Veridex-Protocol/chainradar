"""Collector for Programmatic Web & News search query packs (Brave Search / GDELT)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.config import settings
from src.core.normalizer import extract_effective_domain
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


class WebSearchCollector:
    source_id: str = "web_news_search"
    family: str = "web"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=20, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        items: List[RawItem] = []
        now = datetime.now(timezone.utc)

        # If Brave API Key is provided, execute query
        if not settings.BRAVE_API_KEY:
            return FetchBatch(
                source_id=self.source_id,
                items=[],
                next_cursor=cursor,
                provenance={"status": "disabled_missing_credential"},
            )

        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": settings.BRAVE_API_KEY,
        }
        query = '"public testnet" (blockchain OR rollup OR appchain OR "layer 2")'
        search_url = f"https://api.search.brave.com/res/v1/web/search?q={query}&count=10"

        try:
            resp = await safe_http_client.get(search_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("web", {}).get("results", [])
                for r in results:
                    title = r.get("title", "")
                    url = r.get("url", "")
                    desc = r.get("description", "")

                    payload = {
                        "title": title,
                        "url": url,
                        "description": desc,
                    }
                    c_str = json.dumps(payload, sort_keys=True)
                    c_hash = hashlib.sha256(c_str.encode("utf-8")).hexdigest()

                    items.append(
                        RawItem(
                            source_id=self.source_id,
                            external_id=f"web_{c_hash[:16]}",
                            url=url,
                            source_family=self.family,
                            observed_at=now,
                            raw_payload=payload,
                            content_hash=c_hash,
                            provenance={"source": "brave_search"},
                        )
                    )
        except Exception:
            pass

        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=Cursor(source_id=self.source_id, last_seen_timestamp=now),
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        title = payload.get("title", "")
        desc = payload.get("description", "")
        url = payload.get("url", "")
        combined = f"{title}\n{desc}"

        name = title.split(" - ")[0].split(" | ")[0].strip()
        if not name or len(name) < 2:
            name = "Discovered Web Candidate"

        domains = [extract_effective_domain(url)] if extract_effective_domain(url) else []

        obs = RawObservation(
            candidate_name=name,
            organization_domains=domains,
            stack_family=StackFamily.EVM,
            environment=NetworkEnvironment.TESTNET,
            is_public=True,
            stage=LifecycleStage.S0_RESEARCH_HINT,
            raw_text=combined,
            claims={"web_url": url},
            reliability=0.70,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
