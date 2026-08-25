"""Aptos REST API Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class AptosAdapter:
    family: str = "aptos"

    async def identity(self, endpoint: str) -> NetworkIdentity:
        # GET /v1
        base_url = endpoint.rstrip("/")
        resp = await safe_http_client.get(f"{base_url}/v1")
        data = resp.json()
        chain_id = str(data.get("chain_id", "unknown"))
        ledger_version = data.get("ledger_version")
        git_hash = data.get("git_hash")

        return NetworkIdentity(
            protocol_namespace="aptos",
            chain_id=chain_id,
            display_caip2=format_caip2("aptos", chain_id),
            client_version=git_hash,
            extra=data,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        base_url = endpoint.rstrip("/")
        resp = await safe_http_client.get(f"{base_url}/v1")
        data = resp.json()
        block_height = int(data.get("block_height", data.get("ledger_version", 0)))
        t_usec = data.get("ledger_timestamp")
        block_time = None
        if t_usec:
            block_time = datetime.fromtimestamp(int(t_usec) / 1_000_000, tz=timezone.utc)
        return HeadObservation(
            block_height=block_height,
            block_time=block_time,
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            base_url = endpoint.rstrip("/")
            resp = await safe_http_client.get(f"{base_url}/v1/blocks/by_height/0")
            data = resp.json()
            block_hash = data.get("block_hash")
            return GenesisEvidence(
                genesis_hash=block_hash or "aptos_genesis",
                block0_hash=block_hash,
                raw_data=data,
            )
        except Exception:
            return None
