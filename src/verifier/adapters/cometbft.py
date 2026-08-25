"""Cosmos SDK / CometBFT RPC Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class CometBFTAdapter:
    family: str = "cosmos"

    async def identity(self, endpoint: str) -> NetworkIdentity:
        # endpoint/status
        status_url = endpoint.rstrip("/") + "/status"
        resp = await safe_http_client.get(status_url)
        data = resp.json()
        result = data.get("result", {})
        node_info = result.get("node_info", {})
        network = node_info.get("network", "unknown")
        version = node_info.get("version")

        # Check genesis hash if available
        genesis_hash = None
        genesis_time = None
        try:
            gen_url = endpoint.rstrip("/") + "/genesis"
            gen_resp = await safe_http_client.get(gen_url)
            gen_data = gen_resp.json().get("result", {}).get("genesis", {})
            genesis_time_str = gen_data.get("genesis_time")
            if genesis_time_str:
                genesis_time = datetime.fromisoformat(genesis_time_str.replace("Z", "+00:00"))
        except Exception:
            pass

        return NetworkIdentity(
            protocol_namespace="cosmos",
            chain_id=network,
            display_caip2=format_caip2("cosmos", network),
            client_version=version,
            genesis_hash=genesis_hash,
            genesis_time=genesis_time,
            extra=node_info,
        )

    async def head(self, endpoint: str) -> HeadObservation:
        status_url = endpoint.rstrip("/") + "/status"
        resp = await safe_http_client.get(status_url)
        data = resp.json()
        sync_info = data.get("result", {}).get("sync_info", {})
        height = int(sync_info.get("latest_block_height", 0))
        block_time_str = sync_info.get("latest_block_time")
        block_time = datetime.fromisoformat(block_time_str.replace("Z", "+00:00")) if block_time_str else None
        return HeadObservation(
            block_height=height,
            block_hash=sync_info.get("latest_block_hash"),
            block_time=block_time,
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            gen_url = endpoint.rstrip("/") + "/genesis"
            resp = await safe_http_client.get(gen_url)
            data = resp.json().get("result", {}).get("genesis", {})
            g_time_str = data.get("genesis_time")
            g_time = datetime.fromisoformat(g_time_str.replace("Z", "+00:00")) if g_time_str else None
            g_chain_id = data.get("chain_id", "")
            return GenesisEvidence(
                genesis_hash=g_chain_id,
                genesis_time=g_time,
                raw_data={"chain_id": g_chain_id},
            )
        except Exception:
            return None
