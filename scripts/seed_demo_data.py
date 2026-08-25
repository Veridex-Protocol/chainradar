"""Data seeding script populating realistic early-chain discovery candidates."""

import asyncio
from datetime import datetime, timezone
from src.classifiers.africa import africa_classifier
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.core.pipeline import IntelligencePipeline
from src.core.types import (
    CandidateState,
    LifecycleStage,
    NetworkEnvironment,
    RawItem,
    RawObservation,
    StackFamily,
)
from src.scoring.engine import scoring_engine
from src.storage.database import db_manager
from src.storage.models import (
    AfricaAssessment,
    ChainProduct,
    Contact,
    EvidenceEvent,
    Network,
    NetworkIncarnation,
    ObservationLink,
    Opportunity,
    Organization,
    ScoreSnapshot,
)
from src.storage.repository import Repository


async def seed_data():
    print("🌱 Initializing database and seeding realistic candidates...")
    await db_manager.init_db()

    async with db_manager.session() as session:
        repo = Repository(session)
        pipeline = IntelligencePipeline(session)

        # 1. Kora Network (HOT Candidate - Explicit Nigeria/Kenya Intent)
        kora_obs = RawObservation(
            candidate_name="Kora Network",
            candidate_slug="kora-network",
            organization_name="Kora Foundation",
            organization_domains=["kora.network"],
            github_orgs=["kora-network"],
            stack_family=StackFamily.EVM,
            stack_details="op_stack",
            layer="L2",
            environment=NetworkEnvironment.TESTNET,
            human_chain_id="987654",
            rpc_urls=["https://rpc.testnet.kora.network"],
            explorer_urls=["https://explorer.testnet.kora.network"],
            faucet_urls=["https://faucet.testnet.kora.network"],
            genesis_fingerprint="0x9a8f4c2e1b3d5e7f",
            stage=LifecycleStage.S2_PUBLIC_TESTNET,
            raw_text="Kora Foundation announces Kora Network Sepolia Testnet for Africa expansion. Launching developer grants and hiring an Africa Lead in Lagos, Nigeria and Nairobi, Kenya with M-Pesa on-ramp support.",
            claims={"pr_number": 4201, "author": "kora-dev"},
            contacts=[{
                "role_type": "ecosystem_lead",
                "channel_type": "form",
                "channel_value": "https://kora.network/grants-application",
                "permitted_purpose": "grants_and_partnerships",
                "source_url": "https://kora.network/grants",
            }],
            reliability=0.95,
        )
        raw_kora = RawItem(
            source_id="ethereum_lists",
            external_id="seed_kora_1",
            url="https://github.com/ethereum-lists/chains/pull/4201",
            source_family="registry",
            raw_payload={"title": "Add Kora Network (987654)", "pr_number": 4201},
            content_hash="seed_hash_kora",
        )
        await pipeline.process_raw_item(EthereumListsCollector(), raw_kora)
        cand_kora, _ = await pipeline.resolver.upsert_candidate(kora_obs, "seed_kora_ev")

        # 2. Baobab Rollup (QUALIFIED - Francophone West Africa / Senegal & Cote d'Ivoire)
        baobab_obs = RawObservation(
            candidate_name="Baobab Chain",
            candidate_slug="baobab-chain",
            organization_name="Baobab Labs",
            organization_domains=["baobab.io"],
            github_orgs=["baobab-labs"],
            stack_family=StackFamily.EVM,
            stack_details="arbitrum_orbit",
            layer="L2",
            environment=NetworkEnvironment.TESTNET,
            human_chain_id="554433",
            rpc_urls=["https://rpc.testnet.baobab.io"],
            explorer_urls=["https://scan.testnet.baobab.io"],
            stage=LifecycleStage.S2_PUBLIC_TESTNET,
            raw_text="Lancement de Baobab Chain pour l'Afrique de l'Ouest (Sénégal et Côte d'Ivoire). Programme d'ambassadeurs et intégration Orange Money.",
            claims={"pr_number": 3310},
            reliability=0.90,
        )
        raw_baobab = RawItem(
            source_id="superchain_registry",
            external_id="seed_baobab_1",
            url="https://github.com/ethereum-optimism/superchain-registry/pull/3310",
            source_family="registry",
            raw_payload={"title": "Add Baobab Chain", "pr_number": 3310},
            content_hash="seed_hash_baobab",
        )
        await pipeline.process_raw_item(EthereumListsCollector(), raw_baobab)
        cand_baobab, _ = await pipeline.resolver.upsert_candidate(baobab_obs, "seed_baobab_ev")

        # 3. Nile Layer (QUALIFIED - North Africa / Egypt / Cairo)
        nile_obs = RawObservation(
            candidate_name="Nile L2",
            candidate_slug="nile-l2",
            organization_name="Nile Protocol Foundation",
            organization_domains=["nileprotocol.org"],
            stack_family=StackFamily.STARKNET,
            layer="L2",
            environment=NetworkEnvironment.TESTNET,
            human_chain_id="SN_NILE",
            rpc_urls=["https://rpc.testnet.nileprotocol.org"],
            stage=LifecycleStage.S2_PUBLIC_TESTNET,
            raw_text="إطلاق شبكة النيل للمدفوعات في مصر (Cairo) لدعم الشراكات الإقليمية والتجارة عبر الحدود.",
            claims={"pr_number": 1205},
            reliability=0.88,
        )
        raw_nile = RawItem(
            source_id="github_hyper_search",
            external_id="seed_nile_1",
            url="https://github.com/nileprotocol/nile-core",
            source_family="code",
            raw_payload={"name": "nile-core", "description": "Nile Starknet rollup"},
            content_hash="seed_hash_nile",
        )
        await pipeline.process_raw_item(EthereumListsCollector(), raw_nile)
        cand_nile, _ = await pipeline.resolver.upsert_candidate(nile_obs, "seed_nile_ev")

        # 4. Serengeti Cosmos Hub (RADAR - East Africa / Tanzania)
        serengeti_obs = RawObservation(
            candidate_name="Serengeti Hub",
            candidate_slug="serengeti-hub",
            organization_name="Serengeti Foundation",
            organization_domains=["serengeti.zone"],
            stack_family=StackFamily.COSMOS,
            stack_details="cosmos_sdk",
            layer="L1",
            environment=NetworkEnvironment.DEVNET,
            human_chain_id="serengeti-testnet-1",
            rpc_urls=["https://rpc.devnet.serengeti.zone"],
            stage=LifecycleStage.S1_DEVNET_PROTOTYPE,
            raw_text="Mtandao wa Serengeti Cosmos Hub unazindua devnet nchini Tanzania na Kenya kwa ruzuku za jamii.",
            claims={"cosmos_chain": "serengeti-testnet-1"},
            reliability=0.85,
        )
        raw_serengeti = RawItem(
            source_id="cosmos_chain_registry",
            external_id="seed_serengeti_1",
            url="https://github.com/cosmos/chain-registry/pull/502",
            source_family="registry",
            raw_payload={"chain_name": "serengeti", "chain_id": "serengeti-testnet-1"},
            content_hash="seed_hash_serengeti",
        )
        await pipeline.process_raw_item(EthereumListsCollector(), raw_serengeti)
        cand_serengeti, _ = await pipeline.resolver.upsert_candidate(serengeti_obs, "seed_serengeti_ev")

        print("✅ Demo candidate dataset successfully seeded!")


if __name__ == "__main__":
    asyncio.run(seed_data())
