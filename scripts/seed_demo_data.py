"""Data seeding script populating realistic early-chain discovery candidates."""

import asyncio
from datetime import datetime, timezone
from src.collectors.github.hyper_search import GitHubHyperSearchCollector
from src.collectors.registries.cosmos_registry import CosmosRegistryCollector
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.collectors.registries.superchain import SuperchainCollector
from src.core.pipeline import IntelligencePipeline
from src.core.types import (
    CandidateState,
    LifecycleStage,
    NetworkEnvironment,
    RawItem,
    StackFamily,
)
from src.storage.database import db_manager
from src.storage.repository import Repository


async def seed_data():
    print("🌱 Initializing database and seeding realistic candidates...")
    await db_manager.init_db()

    async with db_manager.session() as session:
        pipeline = IntelligencePipeline(session)

        # 1. Kora Network (HOT Candidate - Explicit Nigeria/Kenya Intent & grants)
        raw_kora = RawItem(
            source_id="ethereum_lists",
            external_id="seed_kora_pr_4201",
            url="https://github.com/ethereum-lists/chains/pull/4201",
            source_family="registry",
            raw_payload={
                "name": "Kora Network",
                "chainId": 987654,
                "rpc": ["https://rpc.testnet.kora.network"],
                "explorers": [{"url": "https://explorer.testnet.kora.network"}],
                "infoURL": "https://kora.network",
                "status": "active",
                "pr_title": "Add Kora Network Sepolia Testnet (987654)",
                "pr_body": "Kora Foundation announces Kora Network Sepolia Testnet for Africa expansion. Launching developer grants and hiring an Africa Lead in Lagos, Nigeria and Nairobi, Kenya with M-Pesa on-ramp support.",
            },
            content_hash="seed_hash_kora_v1",
        )
        await pipeline.process_raw_item(EthereumListsCollector(), raw_kora)

        # 2. Baobab Rollup (QUALIFIED - Francophone West Africa / Senegal & Cote d'Ivoire)
        raw_baobab = RawItem(
            source_id="superchain_registry",
            external_id="seed_baobab_pr_3310",
            url="https://github.com/ethereum-optimism/superchain-registry/pull/3310",
            source_family="registry",
            raw_payload={
                "name": "Baobab Chain",
                "chainId": 554433,
                "rpc": ["https://rpc.testnet.baobab.io"],
                "explorers": [{"url": "https://scan.testnet.baobab.io"}],
                "infoURL": "https://baobab.io",
                "pr_title": "Add Baobab Chain OP Stack L2",
                "pr_body": "Lancement de Baobab Chain pour l'Afrique de l'Ouest (Sénégal et Côte d'Ivoire). Programme d'ambassadeurs et subventions pour développeurs francophones.",
            },
            content_hash="seed_hash_baobab_v1",
        )
        await pipeline.process_raw_item(SuperchainCollector(), raw_baobab)

        # 3. Nile L2 (QUALIFIED - North Africa / Egypt / Cairo)
        raw_nile = RawItem(
            source_id="github_hyper_search",
            external_id="seed_nile_core_repo",
            url="https://github.com/nileprotocol/nile-core",
            source_family="code",
            raw_payload={
                "name": "nile-core",
                "full_name": "nileprotocol/nile-core",
                "description": "إطلاق شبكة النيل للمدفوعات في مصر (Cairo) لدعم الشراكات الإقليمية والتجارة عبر الحدود.",
                "html_url": "https://github.com/nileprotocol/nile-core",
                "stargazers_count": 140,
                "forks_count": 22,
                "created_at": "2026-08-01T10:00:00Z",
            },
            content_hash="seed_hash_nile_v1",
        )
        await pipeline.process_raw_item(GitHubHyperSearchCollector(), raw_nile)

        # 4. Serengeti Hub (RADAR - East Africa / Tanzania)
        raw_serengeti = RawItem(
            source_id="cosmos_chain_registry",
            external_id="seed_serengeti_hub_502",
            url="https://github.com/cosmos/chain-registry/pull/502",
            source_family="registry",
            raw_payload={
                "chain_name": "serengeti",
                "pretty_name": "Serengeti Hub",
                "chain_id": "serengeti-testnet-1",
                "network_type": "testnet",
                "website": "https://serengeti.zone",
                "apis": {"rpc": [{"address": "https://rpc.devnet.serengeti.zone"}]},
                "description": "Mtandao wa Serengeti Cosmos Hub unazindua devnet nchini Tanzania na Kenya kwa ruzuku za jamii.",
            },
            content_hash="seed_hash_serengeti_v1",
        )
        await pipeline.process_raw_item(CosmosRegistryCollector(), raw_serengeti)

        print("✅ Demo candidate dataset successfully seeded!")


if __name__ == "__main__":
    asyncio.run(seed_data())
