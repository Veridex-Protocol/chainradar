"""Substrate / Polkadot SDK JSON-RPC Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class SubstrateAdapter:
    family: str = "substrate"

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
            raise ValueError(f"Substrate RPC error for {method}: {data['error']}")
        return data.get("result")

    async def identity(self, endpoint: str) -> NetworkIdentity:
        system_chain = await self._rpc_call(endpoint, "system_chain")
        
        genesis_hash = None
        try:
            genesis_hash = await self._rpc_call(endpoint, "chain_getBlockHash", [0])
        except Exception:
            pass

        version_info = None
        try:
            version_info = await self._rpc_call(endpoint, "system_version")
        except Exception:
            pass

        chain_id_ref = genesis_hash[:32] if genesis_hash else str(system_chain)

        return NetworkIdentity(
            protocol_namespace="polkadot",
            chain_id=chain_id_ref,
            display_caip2=format_caip2("polkadot", chain_id_ref),
            client_version=str(version_info),
            genesis_hash=genesis_hash,
            block0_hash=genesis_hash,
            extra={"system_chain": system_chain},
        )

    async def head(self, endpoint: str) -> HeadObservation:
        header = await self._rpc_call(endpoint, "chain_getHeader")
        number_hex = header.get("number", "0x0")
        height = int(number_hex, 16) if isinstance(number_hex, str) and number_hex.startswith("0x") else int(number_hex)
        return HeadObservation(
            block_height=height,
            block_hash=header.get("parentHash"),
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            g_hash = await self._rpc_call(endpoint, "chain_getBlockHash", [0])
            return GenesisEvidence(
                genesis_hash=g_hash,
                block0_hash=g_hash,
            )
        except Exception:
            return None
