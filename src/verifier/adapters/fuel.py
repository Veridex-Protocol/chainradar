"""Fuel GraphQL Protocol Adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from src.core.normalizer import format_caip2
from src.core.types import GenesisEvidence, HeadObservation, NetworkIdentity
from src.verifier.safe_url import safe_http_client


class FuelAdapter:
    family: str = "fuel"

    async def _query_graphql(self, endpoint: str, query: str) -> dict:
        payload = {"query": query}
        resp = await safe_http_client.post_json(endpoint, payload)
        data = resp.json()
        if "errors" in data and data["errors"]:
            raise ValueError(f"Fuel GraphQL error: {data['errors']}")
        return data.get("data", {})

    async def identity(self, endpoint: str) -> NetworkIdentity:
        query = """
        query {
            chain {
                name
                consensusParameters {
                    chainId
                }
                latestBlock {
                    header {
                        height
                        id
                    }
                }
            }
        }
        """
        data = await self._query_graphql(endpoint, query)
        chain_info = data.get("chain", {})
        chain_name = chain_info.get("name", "fuel")
        chain_id = str(chain_info.get("consensusParameters", {}).get("chainId", "0"))

        return NetworkIdentity(
            protocol_namespace="fuel",
            chain_id=chain_id,
            display_caip2=format_caip2("fuel", chain_id),
            extra={"name": chain_name},
        )

    async def head(self, endpoint: str) -> HeadObservation:
        query = """
        query {
            chain {
                latestBlock {
                    header {
                        height
                        id
                        time
                    }
                }
            }
        }
        """
        data = await self._query_graphql(endpoint, query)
        latest_block = data.get("chain", {}).get("latestBlock", {})
        header = latest_block.get("header", {})
        height = int(header.get("height", 0))
        block_hash = header.get("id")
        return HeadObservation(
            block_height=height,
            block_hash=block_hash,
            observed_at=datetime.now(timezone.utc),
        )

    async def genesis(self, endpoint: str) -> Optional[GenesisEvidence]:
        try:
            query = """
            query {
                block(height: "0") {
                    id
                    header {
                        time
                    }
                }
            }
            """
            data = await self._query_graphql(endpoint, query)
            block0 = data.get("block", {})
            block_hash = block0.get("id")
            return GenesisEvidence(
                genesis_hash=block_hash or "fuel_genesis",
                block0_hash=block_hash,
            )
        except Exception:
            return None
