"""Collector for Chain Agnostic Namespaces and SLIP-0044 coin types."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.config import settings
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


class CAIPNamespacesCollector:
    source_id: str = "caip_namespaces"
    family: str = "registry"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=20, burst=3)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AshinityEarlyChainDiscovery/1.0",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

        url = "https://api.github.com/repos/ChainAgnostic/namespaces/pulls?state=all&sort=updated&direction=desc&per_page=10"
        items: List[RawItem] = []
        next_etag = cursor.etag

        try:
            resp = await safe_http_client.get(url, headers=headers)
            if resp.status_code == 304:
                return FetchBatch(
                    source_id=self.source_id,
                    items=[],
                    next_cursor=cursor,
                    provenance={"status": 304},
                )
            next_etag = resp.headers.get("etag")
            if resp.status_code == 200:
                prs = resp.json()
                for pr in prs:
                    pr_num = pr.get("number")
                    title = pr.get("title", "")
                    body = pr.get("body", "") or ""
                    updated_at_str = pr.get("updated_at")
                    created_at_str = pr.get("created_at")
                    
                    published_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else None
                    
                    payload = {
                        "pr_number": pr_num,
                        "title": title,
                        "body": body,
                        "state": pr.get("state"),
                        "created_at": created_at_str,
                        "updated_at": updated_at_str,
                        "html_url": pr.get("html_url"),
                    }
                    content_str = json.dumps(payload, sort_keys=True)
                    c_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

                    items.append(
                        RawItem(
                            source_id=self.source_id,
                            external_id=f"caip_pr_{pr_num}_{updated_at_str}",
                            url=pr.get("html_url") or f"https://github.com/ChainAgnostic/namespaces/pull/{pr_num}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            published_at=published_at,
                            raw_payload=payload,
                            headers={"etag": next_etag or ""},
                            content_hash=c_hash,
                            provenance={"source": "ChainAgnostic/namespaces", "pr_number": pr_num},
                        )
                    )
        except Exception:
            pass

        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=Cursor(source_id=self.source_id, etag=next_etag),
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        title = payload.get("title", "")
        body = payload.get("body", "")
        combined = f"{title}\n{body}"

        name = title.replace("Add", "").replace("add", "").replace("namespace", "").strip()
        if not name or len(name) < 2:
            name = f"CAIP Namespace PR #{payload.get('pr_number', 'unknown')}"

        obs = RawObservation(
            candidate_name=name,
            stack_family=StackFamily.CUSTOM,
            environment=NetworkEnvironment.DEVNET,
            is_public=True,
            stage=LifecycleStage.S0_RESEARCH_HINT,
            raw_text=combined,
            claims={"pr_number": payload.get("pr_number")},
            reliability=0.90,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
