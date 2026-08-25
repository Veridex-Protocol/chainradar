"""Starknet JSON-RPC Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class StarknetAdapter:
    family: str = "starknet"

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
            raise ValueError(f"Starknet RPC error for {method}: {data['error']}")
        return data.get("result")

    async def identity(self, endpoint: str) -> NetworkIdentity:
        chain_id_hex = await self._rpc_call(endpoint, "starknet_chainId")
        spec_version = None
        try:
            spec_version = await self._rpc_call(endpoint, "starknet_specVersion")
        except Exception:
            pass

        # Genesis block 0 probe
        genesis_hash = None
        try:
            b0 = await self._rpc_call(endpoint, "starknet_getBlockWithTxHashes", [{"block_number": 0}])
            if b0 and isinstance(b0, dict):
                genesis_hash = b0.get("block_hash")
        except Exception:
            pass

        clean_chain_id = chain_id_hex
        try:
            # Starknet chain IDs are often ascii hex, e.g. 0x534e5f5345504f4c4941 -> SN_SEPOLIA
            if chain_id_hex.startswith("0x"):
                clean_chain_id = bytes.fromhex(chain_id_hex[2:]).decode("utf-8", errors="ignore").strip()
        except Exception:
            pass

        return NetworkIdentity(
            protocol_namespace="starknet",
            chain_id=clean_chain_id or str(chain_id_hex),
            display_caip2=format_caip2("starknet", clean_chain_id or str(chain_id_hex)),
            spec_version=spec_version,
            genesis_hash=genesis_hash,
            block0_hash=genesis_hash,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        block_num = await self._rpc_call(endpoint, "starknet_blockNumber")
        return HeadObservation(
            block_height=int(block_num),
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            b0 = await self._rpc_call(endpoint, "starknet_getBlockWithTxHashes", [{"block_number": 0}])
            if b0 and isinstance(b0, dict):
                g_hash = b0.get("block_hash")
                t = b0.get("timestamp")
                g_time = datetime.fromtimestamp(t, tz=timezone.utc) if t else None
                return GenesisEvidence(
                    genesis_hash=g_hash,
                    genesis_time=g_time,
                    block0_hash=g_hash,
                    raw_data=b0,
                )
        except Exception:
            pass
        return None
