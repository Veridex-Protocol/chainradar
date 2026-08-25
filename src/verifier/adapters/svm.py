"""SVM / Solana Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class SVMAdapter:
    family: str = "svm"

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
            raise ValueError(f"SVM RPC error for {method}: {data['error']}")
        return data.get("result")

    async def identity(self, endpoint: str) -> NetworkIdentity:
        genesis_hash = await self._rpc_call(endpoint, "getGenesisHash")
        version_info = None
        try:
            v_res = await self._rpc_call(endpoint, "getVersion")
            version_info = v_res.get("solana-core") if isinstance(v_res, dict) else str(v_res)
        except Exception:
            pass

        # CAIP-2 for solana uses the genesis hash (or prefix)
        ref = genesis_hash[:32] if genesis_hash else "unknown"
        return NetworkIdentity(
            protocol_namespace="solana",
            chain_id=ref,
            display_caip2=format_caip2("solana", ref),
            client_version=version_info,
            genesis_hash=genesis_hash,
            block0_hash=genesis_hash,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        slot = await self._rpc_call(endpoint, "getSlot")
        return HeadObservation(
            block_height=int(slot),
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            g_hash = await self._rpc_call(endpoint, "getGenesisHash")
            return GenesisEvidence(
                genesis_hash=g_hash,
                block0_hash=g_hash,
            )
        except Exception:
            return None
