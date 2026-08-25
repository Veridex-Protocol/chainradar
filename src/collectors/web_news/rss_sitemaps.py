"""Collector for official RSS/Atom feeds, changelogs, and RaaS provider blogs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
import feedparser
from src.collectors.base import TokenBucketLimiter
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


RAAS_FEEDS = [
    ("conduit_blog", "https://www.conduit.xyz/blog/rss.xml"),
    ("caldera_blog", "https://caldera.xyz/blog/rss.xml"),
    ("gelato_blog", "https://www.gelato.network/blog/rss.xml"),
    ("altlayer_blog", "https://blog.altlayer.io/feed"),
]


class RSSFeedsCollector:
    source_id: str = "rss_sitemaps"
    family: str = "web"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=60, burst=10)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        items: List[RawItem] = []
        now = datetime.now(timezone.utc)

        for feed_name, feed_url in RAAS_FEEDS:
            if not await self.limiter.acquire(1):
                break
            try:
                resp = await safe_http_client.get(feed_url)
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.text)
                    for entry in feed.entries[:10]:
                        title = entry.get("title", "")
                        link = entry.get("link", "")
                        summary = entry.get("summary", "")
                        published = entry.get("published", "")

                        payload = {
                            "feed_name": feed_name,
                            "title": title,
                            "link": link,
                            "summary": summary,
                            "published": published,
                        }
                        c_str = json.dumps(payload, sort_keys=True)
                        c_hash = hashlib.sha256(c_str.encode("utf-8")).hexdigest()

                        items.append(
                            RawItem(
                                source_id=self.source_id,
                                external_id=f"rss_{feed_name}_{c_hash[:16]}",
                                url=link or feed_url,
                                source_family=self.family,
                                observed_at=now,
                                raw_payload=payload,
                                content_hash=c_hash,
                                provenance={"feed_name": feed_name},
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
        summary = payload.get("summary", "")
        link = payload.get("link", "")
        combined = f"{title}\n{summary}"

        # Clean name from title (e.g. "Announcing Kora Network on Conduit")
        name = title
        for prefix in ["Announcing ", "Introducing ", "Welcome ", "Launching "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
        name = name.split(" on ")[0].split(" - ")[0].strip()
        if not name or len(name) < 2:
            name = "RaaS Announced Chain"

        env = NetworkEnvironment.TESTNET
        stage = LifecycleStage.S2_PUBLIC_TESTNET
        if "mainnet" in combined.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED

        domains = []
        if link:
            d = extract_effective_domain(link)
            if d:
                domains.append(d)

        obs = RawObservation(
            candidate_name=name,
            organization_domains=domains,
            stack_family=StackFamily.EVM,
            layer="L2",
            environment=env,
            is_public=True,
            stage=stage,
            raw_text=combined,
            claims={"raas_feed": payload.get("feed_name")},
            reliability=0.85,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
