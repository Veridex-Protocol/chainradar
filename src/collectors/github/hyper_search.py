"""GitHub Hyper-Search collector with sliding 72-hour windows and code artifact detection."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
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


QUERY_PACKS = [
    ("new_blockchain_repos", 'testnet in:name,description,readme topic:blockchain created:>={DATE} archived:false fork:false'),
    ("rollups_appchains", '(rollup OR appchain OR hyperchain) in:name,description,readme created:>={DATE} archived:false fork:false'),
    ("launch_intent", '(mainnet OR devnet OR genesis) in:readme pushed:>={DATE} archived:false fork:false'),
    ("evm_configs", '(chainId OR eth_chainId) (testnet OR mainnet) in:readme pushed:>={DATE}'),
    ("cosmos", '(cosmos-sdk OR cometbft) (testnet OR genesis) in:readme pushed:>={DATE}'),
    ("substrate", '(polkadot-sdk OR substrate OR parachain) (testnet OR chain-spec) in:readme pushed:>={DATE}'),
    ("svm_move_cairo_fuel", '(SVM OR Move OR Cairo OR FuelVM) (testnet OR mainnet OR chain) in:readme pushed:>={DATE}'),
    ("africa_intent", '(Africa OR Nigeria OR Kenya OR Ghana OR Rwanda) (blockchain OR rollup OR chain) in:readme pushed:>={DATE}'),
]


class GitHubHyperSearchCollector:
    source_id: str = "github_hyper_search"
    family: str = "code"

    def __init__(self):
        self.limiter = TokenBucketLimiter(requests_per_minute=30, burst=5)

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ChainRadarDiscovery/1.0",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"

        # Compute 72h sliding window date
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=settings.GITHUB_SEARCH_OVERLAP_HOURS)
        date_str = window_start.strftime("%Y-%m-%d")

        items: List[RawItem] = []
        
        for pack_name, query_template in QUERY_PACKS:
            if not await self.limiter.acquire(1):
                break

            query = query_template.replace("{DATE}", date_str)
            search_url = f"https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=5"

            try:
                resp = await safe_http_client.get(search_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    repos = data.get("items", [])
                    for repo in repos:
                        repo_id = repo.get("id")
                        full_name = repo.get("full_name")
                        html_url = repo.get("html_url")
                        pushed_at_str = repo.get("pushed_at")
                        created_at_str = repo.get("created_at")

                        published_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")) if created_at_str else None
                        
                        payload = {
                            "pack_name": pack_name,
                            "repo_id": repo_id,
                            "full_name": full_name,
                            "name": repo.get("name"),
                            "description": repo.get("description"),
                            "topics": repo.get("topics", []),
                            "homepage": repo.get("homepage"),
                            "created_at": created_at_str,
                            "pushed_at": pushed_at_str,
                            "owner": repo.get("owner", {}).get("login"),
                            "html_url": html_url,
                        }
                        c_str = json.dumps(payload, sort_keys=True)
                        c_hash = hashlib.sha256(c_str.encode("utf-8")).hexdigest()

                        items.append(
                            RawItem(
                                source_id=self.source_id,
                                external_id=f"repo_{repo_id}_{pushed_at_str}",
                                url=html_url,
                                source_family=self.family,
                                observed_at=now,
                                published_at=published_at,
                                raw_payload=payload,
                                content_hash=c_hash,
                                provenance={"pack": pack_name, "repo": full_name},
                            )
                        )
            except Exception:
                pass

        next_cur = Cursor(
            source_id=self.source_id,
            last_seen_timestamp=now,
        )
        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=next_cur,
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        name = payload.get("name", "Unknown Repo")
        desc = payload.get("description", "") or ""
        topics = payload.get("topics", [])
        homepage = payload.get("homepage", "")
        owner = payload.get("owner", "")
        full_text = f"{name} {desc} {' '.join(topics)}"

        # Detect stack family
        stack_family = StackFamily.EVM
        stack_details = None
        if any(t in full_text.lower() for t in ["cosmos-sdk", "cometbft", "tendermint", "cosmos"]):
            stack_family = StackFamily.COSMOS
            stack_details = "cosmos_sdk"
        elif any(t in full_text.lower() for t in ["polkadot-sdk", "substrate", "cumulus", "parachain"]):
            stack_family = StackFamily.SUBSTRATE
            stack_details = "polkadot_sdk"
        elif any(t in full_text.lower() for t in ["svm", "solana-validator", "agave"]):
            stack_family = StackFamily.SVM
        elif any(t in full_text.lower() for t in ["starknet", "cairo"]):
            stack_family = StackFamily.STARKNET
        elif any(t in full_text.lower() for t in ["aptos", "sui", "move"]):
            stack_family = StackFamily.MOVE
        elif any(t in full_text.lower() for t in ["fuel", "fuelvm", "fuel-core"]):
            stack_family = StackFamily.FUEL
        elif "op-stack" in full_text.lower() or "op-geth" in full_text.lower() or "optimism" in full_text.lower():
            stack_family = StackFamily.EVM
            stack_details = "op_stack"
        elif "arbitrum" in full_text.lower() or "nitro" in full_text.lower():
            stack_family = StackFamily.EVM
            stack_details = "arbitrum_orbit"

        # Detect layer
        layer = "L2"
        if any(t in full_text.lower() for t in ["layer 1", "l1", "sovereign"]):
            layer = "L1"
        elif any(t in full_text.lower() for t in ["layer 3", "l3", "hyperchain"]):
            layer = "L3"

        # Detect stage
        stage = LifecycleStage.S1_DEVNET_PROTOTYPE
        env = NetworkEnvironment.DEVNET
        if "mainnet" in full_text.lower():
            env = NetworkEnvironment.MAINNET
            stage = LifecycleStage.S4_MAINNET_ANNOUNCED
        elif "incentivized" in full_text.lower():
            env = NetworkEnvironment.TESTNET
            stage = LifecycleStage.S3_INCENTIVIZED_TESTNET
        elif "testnet" in full_text.lower():
            env = NetworkEnvironment.TESTNET
            stage = LifecycleStage.S2_PUBLIC_TESTNET

        domains = []
        if homepage:
            d = extract_effective_domain(homepage)
            if d:
                domains.append(d)

        claims = {
            "pack_name": payload.get("pack_name"),
            "github_repo": payload.get("full_name"),
        }
        if payload.get("created_at"):
            claims["repo_created_at"] = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))

        obs = RawObservation(
            candidate_name=name,
            organization_name=owner,
            organization_domains=domains,
            github_orgs=[owner] if owner else [],
            stack_family=stack_family,
            stack_details=stack_details,
            layer=layer,
            environment=env,
            is_public=True,
            stage=stage,
            raw_text=full_text,
            claims=claims,
            reliability=0.80,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
