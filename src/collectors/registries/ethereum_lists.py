"""Collector for ethereum-lists/chains registry PRs and merged chain definitions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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


class EthereumListsCollector:
    source_id: str = "ethereum_lists"
    family: str = "registry"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=60, burst=10)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        """Fetches recent PRs or commits from ethereum-lists/chains via GitHub API."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AshinityEarlyChainDiscovery/1.0",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

        url = "https://api.github.com/repos/ethereum-lists/chains/pulls?state=all&sort=updated&direction=desc&per_page=20"
        
        items: List[RawItem] = []
        next_etag = cursor.etag
        
        try:
            resp = await safe_http_client.get(url, headers=headers)
            if resp.status_code == 304:
                # No changes
                return FetchBatch(
                    source_id=self.source_id,
                    items=[],
                    next_cursor=cursor,
                    provenance={"status": 304, "checked_at": str(datetime.now(timezone.utc))},
                )
            
            next_etag = resp.headers.get("etag")
            if resp.status_code == 200:
                prs = resp.json()
                for pr in prs:
                    pr_num = pr.get("number")
                    pr_title = pr.get("title", "")
                    pr_body = pr.get("body", "") or ""
                    updated_at_str = pr.get("updated_at")
                    created_at_str = pr.get("created_at")
                    merged_at_str = pr.get("merged_at")
                    
                    published_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else None
                    
                    payload = {
                        "pr_number": pr_num,
                        "title": pr_title,
                        "body": pr_body,
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
                            external_id=f"pr_{pr_num}_{updated_at_str}",
                            url=pr.get("html_url") or f"https://github.com/ethereum-lists/chains/pull/{pr_num}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            published_at=published_at,
                            raw_payload=payload,
                            headers={"etag": next_etag or ""},
                            content_hash=c_hash,
                            provenance={"source": "ethereum-lists/chains", "pr_number": pr_num},
                        )
                    )
        except Exception as e:
            # Fallback gracefully
            pass

        next_cur = Cursor(
            source_id=self.source_id,
            etag=next_etag,
            last_seen_timestamp=datetime.now(timezone.utc),
        )
        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=next_cur,
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        """Parses chain fields from GitHub PR payload or chain JSON data."""
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        
        # If payload is a direct chain JSON definition
        if "chainId" in payload or "chain" in payload:
            chain_id = str(payload.get("chainId", ""))
            name = payload.get("name") or payload.get("chain", "Unknown Chain")
            rpcs = [r for r in payload.get("rpc", []) if isinstance(r, str) and not r.startswith("wss://")]
            explorers = [e.get("url") for e in payload.get("explorers", []) if isinstance(e, dict) and e.get("url")]
            faucets = payload.get("faucets", [])
            info_url = payload.get("infoURL", "")
            
            domains = []
            if info_url:
                d = extract_effective_domain(info_url)
                if d:
                    domains.append(d)

            stage = LifecycleStage.S1_DEVNET_PROTOTYPE
            env = NetworkEnvironment.TESTNET
            status = str(payload.get("status", "")).lower()
            if status == "active" or "mainnet" in name.lower():
                env = NetworkEnvironment.MAINNET
                stage = LifecycleStage.S4_MAINNET_ANNOUNCED
            elif "testnet" in name.lower() or "sepolia" in name.lower() or "devnet" in name.lower():
                stage = LifecycleStage.S2_PUBLIC_TESTNET

            obs = RawObservation(
                candidate_name=name,
                organization_domains=domains,
                stack_family=StackFamily.EVM,
                layer="L2" if payload.get("parent") else "L1",
                environment=env,
                is_public=True,
                caip2=format_caip2("eip155", chain_id) if chain_id else None,
                protocol_namespace="eip155",
                human_chain_id=chain_id,
                rpc_urls=rpcs,
                explorer_urls=explorers,
                faucet_urls=faucets,
                stage=stage,
                raw_text=json.dumps(payload),
                claims={"parent": payload.get("parent")},
                reliability=0.90,
            )
            return [obs]

        # Else parse from PR title and body
        title = payload.get("title", "")
        body = payload.get("body", "")
        combined_text = f"{title}\n{body}"

        # Extract name from PR title (e.g. "Add Kora Network (chainId: 987654)" or "Add MyChain testnet")
        name = title.replace("Add", "").replace("add", "").replace("Chain:", "").replace("chain:", "").split("(")[0].strip()
        if not name or len(name) < 2:
            name = f"Chain PR #{payload.get('pr_number', 'unknown')}"

        # Search for chainId in title or body
        chain_id = None
        import re
        m = re.search(r"chainId[:\s=]+(\d+)", combined_text, re.IGNORECASE)
        if m:
            chain_id = m.group(1)

        # Search for RPC URL in body
        rpcs = []
        m_rpc = re.findall(r"https?://[^\s<>\"']+(?:rpc|node)[^\s<>\"']*", combined_text, re.IGNORECASE)
        if m_rpc:
            rpcs = list(set(m_rpc))

        # Search for explorer URL
        explorers = []
        m_exp = re.findall(r"https?://[^\s<>\"']+(?:explorer|scan)[^\s<>\"']*", combined_text, re.IGNORECASE)
        if m_exp:
            explorers = list(set(m_exp))

        # Determine environment
        env = NetworkEnvironment.TESTNET
        stage = LifecycleStage.S1_DEVNET_PROTOTYPE
        if "mainnet" in combined_text.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED
        elif "testnet" in combined_text.lower():
            stage = LifecycleStage.S2_PUBLIC_TESTNET

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
            stack_family=StackFamily.EVM,
            environment=env,
            is_public=True,
            caip2=format_caip2("eip155", chain_id) if chain_id else None,
            protocol_namespace="eip155",
            human_chain_id=chain_id,
            rpc_urls=rpcs,
            explorer_urls=explorers,
            stage=stage,
            raw_text=combined_text,
            claims=claims,
            reliability=0.90,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
