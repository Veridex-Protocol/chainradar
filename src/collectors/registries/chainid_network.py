"""Collector for chainid.network aggregated chains snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from src.collectors.base import TokenBucketLimiter
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


class ChainIdNetworkCollector:
    source_id: str = "chainid_network"
    family: str = "registry"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=20, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        url = "https://chainid.network/chains.json"
        headers = {}
        if cursor.etag:
            headers["If-None-Match"] = cursor.etag

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
                chains = resp.json()
                for c in chains:
                    c_id = c.get("chainId")
                    name = c.get("name", "Unknown Chain")
                    content_str = json.dumps(c, sort_keys=True)
                    c_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

                    items.append(
                        RawItem(
                            source_id=self.source_id,
                            external_id=f"chain_{c_id}",
                            url=f"https://chainid.network/chains.json#{c_id}",
                            source_family=self.family,
                            observed_at=datetime.now(timezone.utc),
                            raw_payload=c,
                            headers={"etag": next_etag or ""},
                            content_hash=c_hash,
                            provenance={"source": "chainid.network"},
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
        chain_id = str(payload.get("chainId", ""))
        name = payload.get("name") or payload.get("chain", "Unknown Chain")
        rpcs = [r for r in payload.get("rpc", []) if isinstance(r, str) and not r.startswith("wss://")]
        faucets = payload.get("faucets", [])
        explorers = [e.get("url") for e in payload.get("explorers", []) if isinstance(e, dict) and e.get("url")]
        info_url = payload.get("infoURL", "")

        domains = []
        if info_url:
            d = extract_effective_domain(info_url)
            if d:
                domains.append(d)

        env = NetworkEnvironment.TESTNET
        stage = LifecycleStage.S2_PUBLIC_TESTNET
        status = str(payload.get("status", "")).lower()
        if status == "active" or "mainnet" in name.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED

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
            claims={"parent": payload.get("parent"), "nativeCurrency": payload.get("nativeCurrency")},
            reliability=0.88,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
