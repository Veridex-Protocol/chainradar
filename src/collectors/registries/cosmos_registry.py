"""Collector for Cosmos Chain Registry."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
from src.config import settings
from src.core.normalizer import extract_effective_domain, format_caip2
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


class CosmosRegistryCollector:
    source_id: str = "cosmos_chain_registry"
    family: str = "registry"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=40, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ChainRadarDiscovery/1.0",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

        url = "https://api.github.com/repos/cosmos/chain-registry/pulls?state=all&sort=updated&direction=desc&per_page=15"
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
                            external_id=f"cosmos_pr_{pr_num}_{updated_at_str}",
                            url=pr.get("html_url") or f"https://github.com/cosmos/chain-registry/pull/{pr_num}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            published_at=published_at,
                            raw_payload=payload,
                            headers={"etag": next_etag or ""},
                            content_hash=c_hash,
                            provenance={"source": "cosmos/chain-registry", "pr_number": pr_num},
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
        
        # If payload is a direct cosmos chain.json
        if "chain_name" in payload or "chain_id" in payload:
            chain_id = payload.get("chain_id", "")
            name = payload.get("pretty_name") or payload.get("chain_name", "Unknown Cosmos Chain")
            status = payload.get("status", "live")
            net_type = payload.get("network_type", "mainnet")
            
            apis = payload.get("apis", {})
            rpcs = [r.get("address") for r in apis.get("rpc", []) if isinstance(r, dict) and r.get("address")]
            explorers = [e.get("url") for e in payload.get("explorers", []) if isinstance(e, dict) and e.get("url")]
            website = payload.get("website", "")
            domains = [extract_effective_domain(website)] if extract_effective_domain(website) else []

            env = NetworkEnvironment.TESTNET if net_type == "testnet" or "test" in chain_id else NetworkEnvironment.MAINNET
            stage = LifecycleStage.S2_PUBLIC_TESTNET if env == NetworkEnvironment.TESTNET else LifecycleStage.S5_EARLY_MAINNET

            obs = RawObservation(
                candidate_name=name,
                organization_domains=domains,
                stack_family=StackFamily.COSMOS,
                stack_details="cosmos_sdk",
                layer="L1",
                environment=env,
                is_public=True,
                caip2=format_caip2("cosmos", chain_id) if chain_id else None,
                protocol_namespace="cosmos",
                human_chain_id=chain_id,
                rpc_urls=rpcs,
                explorer_urls=explorers,
                stage=stage,
                raw_text=json.dumps(payload),
                claims={"codebase": payload.get("codebase"), "bech32_prefix": payload.get("bech32_prefix")},
                reliability=0.92,
            )
            return [obs]

        # Else parse from PR
        title = payload.get("title", "")
        body = payload.get("body", "")
        combined = f"{title}\n{body}"

        name = title.replace("Add", "").replace("add", "").replace("chain", "").strip()
        if not name or len(name) < 2:
            name = f"Cosmos PR #{payload.get('pr_number', 'unknown')}"

        import re
        m_id = re.search(r"chain_id[:\s=]+([\w-]+)", combined, re.IGNORECASE)
        chain_id = m_id.group(1) if m_id else None

        rpcs = re.findall(r"https?://[^\s<>\"']+(?:rpc|node)[^\s<>\"']*", combined, re.IGNORECASE)
        explorers = re.findall(r"https?://[^\s<>\"']+(?:explorer|mintscan)[^\s<>\"']*", combined, re.IGNORECASE)

        env = NetworkEnvironment.TESTNET
        stage = LifecycleStage.S2_PUBLIC_TESTNET
        if "mainnet" in combined.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED

        claims = {
            "pr_number": payload.get("pr_number"),
            "author": payload.get("user"),
        }
        if payload.get("created_at"):
            claims["registry_pr_opened_at"] = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
        if payload.get("merged_at"):
            claims["registry_merged_at"] = datetime.fromisoformat(payload["merged_at"].replace("Z", "+00:00"))

        obs = RawObservation(
            candidate_name=name,
            stack_family=StackFamily.COSMOS,
            stack_details="cosmos_sdk",
            layer="L1",
            environment=env,
            is_public=True,
            caip2=format_caip2("cosmos", chain_id) if chain_id else None,
            protocol_namespace="cosmos",
            human_chain_id=chain_id,
            rpc_urls=list(set(rpcs)),
            explorer_urls=list(set(explorers)),
            stage=stage,
            raw_text=combined,
            claims=claims,
            reliability=0.92,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
