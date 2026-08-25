"""EVM JSON-RPC Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.core.normalizer import format_caip2, normalize_chain_id
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class EVMAdapter:
    family: str = "evm"

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
            raise ValueError(f"RPC error for {method}: {data['error']}")
        return data.get("result")

    async def identity(self, endpoint: str) -> NetworkIdentity:
        # eth_chainId
        chain_id_hex = await self._rpc_call(endpoint, "eth_chainId")
        chain_id_dec = normalize_chain_id(chain_id_hex)
        
        # web3_clientVersion
        client_version = None
        try:
            client_version = await self._rpc_call(endpoint, "web3_clientVersion")
        except Exception:
            pass

        # Genesis block 0 probe
        genesis_hash = None
        try:
            b0 = await self._rpc_call(endpoint, "eth_getBlockByNumber", ["0x0", False])
            if b0 and isinstance(b0, dict):
                genesis_hash = b0.get("hash")
        except Exception:
            pass

        return NetworkIdentity(
            protocol_namespace="eip155",
            chain_id=chain_id_dec or str(chain_id_hex),
            display_caip2=format_caip2("eip155", chain_id_dec or str(chain_id_hex)),
            client_version=client_version,
            genesis_hash=genesis_hash,
            block0_hash=genesis_hash,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        block_num_hex = await self._rpc_call(endpoint, "eth_blockNumber")
        height = 0
        if isinstance(block_num_hex, str) and block_num_hex.startswith("0x"):
            height = int(block_num_hex, 16)
        elif block_num_hex is not None:
            height = int(block_num_hex)
        return HeadObservation(
            block_height=height,
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            b0 = await self._rpc_call(endpoint, "eth_getBlockByNumber", ["0x0", False])
            if b0 and isinstance(b0, dict):
                g_hash = b0.get("hash")
                t_hex = b0.get("timestamp")
                g_time = datetime.fromtimestamp(int(t_hex, 16), tz=timezone.utc) if t_hex else None
                return GenesisEvidence(
                    genesis_hash=g_hash,
                    genesis_time=g_time,
                    block0_hash=g_hash,
                    raw_data=b0,
                )
        except Exception:
            pass
        return None
