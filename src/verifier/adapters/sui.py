"""Sui Move JSON-RPC Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class SuiAdapter:
    family: str = "sui"

    async def _rpc_call(self, endpoint: str, method: str, params: list = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or [],
            "id": 1,
        }
        resp = await safe_http_client.post_json(endpoint, payload)
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Sui RPC error for {method}: {data['error']}")
        return data.get("result")

    async def identity(self, endpoint: str) -> NetworkIdentity:
        chain_identifier = None
        try:
            chain_identifier = await self._rpc_call(endpoint, "sui_getChainIdentifier")
        except Exception:
            chain_identifier = await self._rpc_call(endpoint, "suix_getChainIdentifier")

        ref = str(chain_identifier) if chain_identifier else "unknown"
        return NetworkIdentity(
            protocol_namespace="sui",
            chain_id=ref,
            display_caip2=format_caip2("sui", ref),
            genesis_hash=ref,
            block0_hash=ref,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        seq_num = await self._rpc_call(endpoint, "sui_getLatestCheckpointSequenceNumber")
        return HeadObservation(
            block_height=int(seq_num),
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            cp0 = await self._rpc_call(endpoint, "sui_getCheckpoint", ["0"])
            digest = cp0.get("digest") if isinstance(cp0, dict) else str(cp0)
            return GenesisEvidence(
                genesis_hash=digest or "sui_genesis",
                block0_hash=digest,
                raw_data=cp0 if isinstance(cp0, dict) else None,
            )
        except Exception:
            return None
