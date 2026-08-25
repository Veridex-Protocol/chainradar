"""Collector for Optimism Superchain Registry."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.config import settings
from src.core.normalizer import format_caip2, normalize_chain_id
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


class SuperchainCollector:
    source_id: str = "superchain_registry"
    family: str = "registry"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=30, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ChainRadarDiscovery/1.0",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

        url = "https://api.github.com/repos/ethereum-optimism/superchain-registry/pulls?state=all&sort=updated&direction=desc&per_page=15"
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
                    merged_at_str = pr.get("merged_at")
                    
                    published_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else None
                    
                    payload = {
                        "pr_number": pr_num,
                        "title": title,
                        "body": body,
                        "state": pr.get("state"),
                        "created_at": created_at_str,
                        "updated_at": updated_at_str,
                        "merged_at": merged_at_str,
                        "user": pr.get("user", {}).get("login"),
                        "html_url": pr.get("html_url"),
                    }
                    content_str = json.dumps(payload, sort_keys=True)
                    c_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

                    items.append(
                        RawItem(
                            source_id=self.source_id,
                            external_id=f"superchain_pr_{pr_num}_{updated_at_str}",
                            url=pr.get("html_url") or f"https://github.com/ethereum-optimism/superchain-registry/pull/{pr_num}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            published_at=published_at,
                            raw_payload=payload,
                            headers={"etag": next_etag or ""},
                            content_hash=c_hash,
                            provenance={"source": "superchain-registry", "pr_number": pr_num},
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

        # Clean name
        name = title.replace("Add", "").replace("add", "").replace("chain", "").replace("Chain", "").strip()
        if not name or len(name) < 2:
            name = f"OP Superchain PR #{payload.get('pr_number', 'unknown')}"

        import re
        m = re.search(r"chain_id[:\s=]+(\d+)", combined, re.IGNORECASE)
        chain_id = m.group(1) if m else None

        rpcs = re.findall(r"https?://[^\s<>\"']+(?:rpc|node)[^\s<>\"']*", combined, re.IGNORECASE)
        explorers = re.findall(r"https?://[^\s<>\"']+(?:explorer|scan)[^\s<>\"']*", combined, re.IGNORECASE)

        env = NetworkEnvironment.TESTNET
        stage = LifecycleStage.S2_PUBLIC_TESTNET
        if "mainnet" in combined.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED

        claims = {
            "pr_number": payload.get("pr_number"),
            "superchain_level": "standard",
        }
        if payload.get("created_at"):
            claims["registry_pr_opened_at"] = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
        if payload.get("merged_at"):
            claims["registry_merged_at"] = datetime.fromisoformat(payload["merged_at"].replace("Z", "+00:00"))

        obs = RawObservation(
            candidate_name=name,
            stack_family=StackFamily.EVM,
            stack_details="op_stack",
            layer="L2",
            environment=env,
            is_public=True,
            caip2=format_caip2("eip155", chain_id) if chain_id else None,
            protocol_namespace="eip155",
            human_chain_id=chain_id,
            rpc_urls=list(set(rpcs)),
            explorer_urls=list(set(explorers)),
            stage=stage,
            raw_text=combined,
            claims=claims,
            reliability=0.95,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
