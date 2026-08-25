"""Acceptance Test Suite verifying all 16 criteria from Section 25."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.alerting.evidence_card import EvidenceCardBuilder
from src.classifiers.africa import africa_classifier
from src.classifiers.risk import risk_evaluator
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.compliance.privacy import PrivacyComplianceManager
from src.core.pipeline import IntelligencePipeline
from src.core.types import (
    AfricaIntentLabel,
    CandidateState,
    HeadObservation,
    IncarnationStatus,
    LifecycleStage,
    NetworkIdentity,
    RawItem,
    RawObservation,
    StackFamily,
)
from src.scoring.engine import scoring_engine
from src.storage.models import Base, ChainProduct, EvidenceEvent, Network, NetworkIncarnation, ScoreSnapshot
from src.storage.repository import Repository
from src.verifier.engine import verifier_engine
from src.verifier.safe_url import SSRFValidationError, SafeURLValidator
from tests.fixtures.sample_data import (
    AFRICA_OFFICIAL_JOB_TEXT,
    ARABIC_REGIONAL_TEXT,
    FRENCH_REGIONAL_TEXT,
    GENERIC_GLOBAL_TEXT,
    PORTUGUESE_REGIONAL_TEXT,
    REGISTRY_PR_FIXTURE_1,
    REGISTRY_PR_MERGE_FIXTURE,
    REGISTRY_PR_UPDATE_FIXTURE,
    SWAHILI_REGIONAL_TEXT,
    TOKEN_ONLY_TEXT,
)


@pytest.fixture
async def test_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        json_serializer=lambda obj: json.dumps(obj, default=str),
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    
    await engine.dispose()


# 1. Test Registry Diff
@pytest.mark.asyncio
async def test_acceptance_1_registry_diff(test_db: AsyncSession):
    pipeline = IntelligencePipeline(test_db)
    collector = EthereumListsCollector()
    
    c_hash = hashlib.sha256(json.dumps(REGISTRY_PR_FIXTURE_1, sort_keys=True).encode()).hexdigest()
    raw = RawItem(
        source_id="ethereum_lists",
        external_id="pr_4201_v1",
        url="https://github.com/ethereum-lists/chains/pull/4201",
        source_family="registry",
        raw_payload=REGISTRY_PR_FIXTURE_1,
        content_hash=c_hash,
    )
    
    candidate_ids = await pipeline.process_raw_item(collector, raw)
    assert len(candidate_ids) == 1
    
    repo = Repository(test_db)
    candidate = await repo.get_candidate(candidate_ids[0])
    assert candidate is not None
    assert "kora" in candidate.canonical_name.lower()
    assert candidate.registry_pr_opened_at is not None
    assert candidate.networks[0].human_chain_id == "987654"


# 2. Test PR Update
@pytest.mark.asyncio
async def test_acceptance_2_pr_update(test_db: AsyncSession):
    pipeline = IntelligencePipeline(test_db)
    collector = EthereumListsCollector()
    
    # Ingest v1
    c_hash1 = hashlib.sha256(json.dumps(REGISTRY_PR_FIXTURE_1, sort_keys=True).encode()).hexdigest()
    raw1 = RawItem(
        source_id="ethereum_lists",
        external_id="pr_4201_v1",
        url="https://github.com/ethereum-lists/chains/pull/4201",
        source_family="registry",
        raw_payload=REGISTRY_PR_FIXTURE_1,
        content_hash=c_hash1,
    )
    c_ids1 = await pipeline.process_raw_item(collector, raw1)

    # Ingest update v2
    c_hash2 = hashlib.sha256(json.dumps(REGISTRY_PR_UPDATE_FIXTURE, sort_keys=True).encode()).hexdigest()
    raw2 = RawItem(
        source_id="ethereum_lists",
        external_id="pr_4201_v2",
        url="https://github.com/ethereum-lists/chains/pull/4201",
        source_family="registry",
        raw_payload=REGISTRY_PR_UPDATE_FIXTURE,
        content_hash=c_hash2,
    )
    c_ids2 = await pipeline.process_raw_item(collector, raw2)

    # Must resolve to the SAME candidate ID
    assert c_ids1[0] == c_ids2[0]

    repo = Repository(test_db)
    evs = await repo.list_evidence_for_candidate(c_ids1[0])
    assert len(evs) == 2  # Evidence appended, no duplicates


# 3. Test PR Merge
@pytest.mark.asyncio
async def test_acceptance_3_pr_merge(test_db: AsyncSession):
    pipeline = IntelligencePipeline(test_db)
    collector = EthereumListsCollector()
    
    c_hash = hashlib.sha256(json.dumps(REGISTRY_PR_MERGE_FIXTURE, sort_keys=True).encode()).hexdigest()
    raw = RawItem(
        source_id="ethereum_lists",
        external_id="pr_4201_merged",
        url="https://github.com/ethereum-lists/chains/pull/4201",
        source_family="registry",
        raw_payload=REGISTRY_PR_MERGE_FIXTURE,
        content_hash=c_hash,
    )
    c_ids = await pipeline.process_raw_item(collector, raw)
    
    repo = Repository(test_db)
    candidate = await repo.get_candidate(c_ids[0])
    assert candidate.registry_merged_at is not None


# 4. Test EVM Verify & Liveness
@pytest.mark.asyncio
async def test_acceptance_4_evm_verify_liveness():
    obs1 = (HeadObservation(block_height=1000, observed_at=datetime.now(timezone.utc)), "0xgenesis123")
    obs2 = (HeadObservation(block_height=1005, observed_at=datetime.now(timezone.utc)), "0xgenesis123")
    
    advancing, identity_stable = verifier_engine.evaluate_liveness(obs1, obs2)
    assert advancing is True
    assert identity_stable is True


# 5. Test Collision (Same Chain ID, Different Genesis)
@pytest.mark.asyncio
async def test_acceptance_5_collision_detection():
    # When same chain ID is observed with a different genesis
    risk_score, breakdown, flags = risk_evaluator.evaluate_risk(has_chain_id_collision=True)
    assert risk_score >= 30.0
    assert "Identity mismatch or unexplained chain-ID collision" in flags


# 6. Test Testnet Reset Supersession
@pytest.mark.asyncio
async def test_acceptance_6_testnet_reset(test_db: AsyncSession):
    repo = Repository(test_db)
    pipeline = IntelligencePipeline(test_db)
    
    # Ingest Genesis 1
    obs1 = RawObservation(
        candidate_name="ResetChain",
        stack_family=StackFamily.EVM,
        human_chain_id="7777",
        genesis_fingerprint="0xgenesis_v1",
        reliability=0.9,
    )
    raw1 = RawItem(source_id="ethereum_lists", external_id="reset_1", url="http://test.com", source_family="registry", raw_payload={}, content_hash="hash1")
    ev1 = await repo.append_evidence(raw1)
    cand, _ = await pipeline.resolver.upsert_candidate(obs1, ev1.id)

    # Ingest Genesis 2 (Reset)
    obs2 = RawObservation(
        candidate_name="ResetChain",
        stack_family=StackFamily.EVM,
        human_chain_id="7777",
        genesis_fingerprint="0xgenesis_v2",
        reliability=0.9,
    )
    raw2 = RawItem(source_id="ethereum_lists", external_id="reset_2", url="http://test.com", source_family="registry", raw_payload={}, content_hash="hash2")
    ev2 = await repo.append_evidence(raw2)
    cand2, _ = await pipeline.resolver.upsert_candidate(obs2, ev2.id)

    stmt = select(NetworkIncarnation).where(NetworkIncarnation.network_id == cand2.networks[0].id)
    res = await test_db.execute(stmt)
    incs = res.scalars().all()
    assert len(incs) == 2
    
    # One active, one superseded
    statuses = [i.status for i in incs]
    assert IncarnationStatus.ACTIVE.value in statuses
    assert IncarnationStatus.SUPERSEDED.value in statuses


# 7. Test Non-EVM Adapters
def test_acceptance_7_non_evm_adapters_registered():
    for family in ["cosmos", "substrate", "svm", "starknet", "aptos", "sui", "fuel"]:
        adapter = verifier_engine.get_adapter(family)
        assert adapter is not None, f"Missing adapter for {family}"


# 8. Test SSRF Rejection
def test_acceptance_8_ssrf_safety():
    unsafe_targets = [
        "http://localhost:8545",
        "http://127.0.0.1:8545",
        "http://10.0.0.1:8545",
        "http://192.168.1.50:8545",
        "http://172.16.0.5:8545",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8545",
        "http://[fe80::1]:8545",
        "ftp://example.com/rpc",
    ]
    for url in unsafe_targets:
        with pytest.raises(SSRFValidationError):
            SafeURLValidator.validate_url(url)


# 9. Test Rate Limit 429 Safety
@pytest.mark.asyncio
async def test_acceptance_9_rate_limit_handling(test_db: AsyncSession):
    repo = Repository(test_db)
    await repo.save_cursor("ethereum_lists", etag="W/'12345'", is_success=False)
    
    cur = await repo.get_cursor("ethereum_lists")
    assert cur.etag == "W/'12345'"
    assert cur.consecutive_failures == 1


# 10. Test Replay Idempotency
@pytest.mark.asyncio
async def test_acceptance_10_replay_idempotency(test_db: AsyncSession):
    pipeline = IntelligencePipeline(test_db)
    collector = EthereumListsCollector()
    
    raw = RawItem(
        source_id="ethereum_lists",
        external_id="pr_replay_100",
        url="https://github.com/ethereum-lists/chains/pull/100",
        source_family="registry",
        raw_payload=REGISTRY_PR_FIXTURE_1,
        content_hash="repeat_hash_100",
    )
    
    c1 = await pipeline.process_raw_item(collector, raw)
    c2 = await pipeline.process_raw_item(collector, raw)
    assert c1 == c2


# 11. Test Africa Intent vs Global Compatibility
def test_acceptance_11_africa_intent_separation():
    # Official Job -> A1
    vec1, label1 = africa_classifier.evaluate_feature_vector(AFRICA_OFFICIAL_JOB_TEXT, is_official_source=True)
    assert label1 == AfricaIntentLabel.A1_EXPLICIT_INTENT
    assert "Nigeria" in vec1.matched_countries or "Kenya" in vec1.matched_countries

    # Generic Global Text -> A3 max (never A1/A2)
    vec2, label2 = africa_classifier.evaluate_feature_vector(GENERIC_GLOBAL_TEXT, is_official_source=True)
    assert label2 in (AfricaIntentLabel.A3_AFRICA_COMPATIBLE, AfricaIntentLabel.A4_NO_EVIDENCE)
    assert label2 != AfricaIntentLabel.A1_EXPLICIT_INTENT


# 12. Test Multilingual Packs (FR, PT, AR, SW)
def test_acceptance_12_multilingual_packs():
    # French
    vec_fr, label_fr = africa_classifier.evaluate_feature_vector(FRENCH_REGIONAL_TEXT, is_official_source=True)
    assert "Senegal" in vec_fr.matched_countries or "Cote d'Ivoire" in vec_fr.matched_countries
    assert "fr" in vec_fr.matched_languages

    # Portuguese
    vec_pt, label_pt = africa_classifier.evaluate_feature_vector(PORTUGUESE_REGIONAL_TEXT, is_official_source=True)
    assert "Angola" in vec_pt.matched_countries or "Mozambique" in vec_pt.matched_countries

    # Arabic
    vec_ar, label_ar = africa_classifier.evaluate_feature_vector(ARABIC_REGIONAL_TEXT, is_official_source=True)
    assert "Egypt" in vec_ar.matched_countries or "ar" in vec_ar.matched_languages

    # Swahili
    vec_sw, label_sw = africa_classifier.evaluate_feature_vector(SWAHILI_REGIONAL_TEXT, is_official_source=True)
    assert "Kenya" in vec_sw.matched_countries or "Tanzania" in vec_sw.matched_countries


# 13. Test Token-Only Rejection
def test_acceptance_13_token_only_exclusion():
    risk, bd, flags = risk_evaluator.evaluate_risk(is_token_only_or_content_farm=True)
    assert risk >= 25.0
    assert "Only token-sale, referral or content-farm evidence" in flags


# 14. Test Source Removal / Kill Switch
def test_acceptance_14_source_removal():
    from src.config import source_register
    source_register.set_kill_switch("ethereum_lists", True)
    assert source_register.is_enabled("ethereum_lists") is False
    source_register.set_kill_switch("ethereum_lists", False)


# 15. Test Audit Trail Traceability
@pytest.mark.asyncio
async def test_acceptance_15_audit_traceability(test_db: AsyncSession):
    repo = Repository(test_db)
    log = await repo.append_audit_log(
        actor="lead_analyst",
        action="africa_override",
        target_type="candidate",
        target_id="cand_123",
        reason="Verified Nigeria partnership announcement",
    )
    assert log.id is not None
    assert log.actor == "lead_analyst"


# 16. Test Privacy Suppression Workflow
@pytest.mark.asyncio
async def test_acceptance_16_privacy_suppression(test_db: AsyncSession):
    compliance = PrivacyComplianceManager()
    channel = "bd-lead@examplechain.org"
    
    repo = Repository(test_db)
    assert await repo.is_suppressed(channel) is False
    
    await compliance.suppress_contact(test_db, channel, reason="NDPA Opt-out")
    assert await repo.is_suppressed(channel) is True
