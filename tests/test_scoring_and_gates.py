"""Tests for Discovery Confidence, Momentum, Africa Fit, Risk, and Outreach Gate State Machine."""

from datetime import datetime, timezone
import pytest
from src.core.types import CandidateState, LifecycleStage
from src.scoring.confidence import confidence_scorer
from src.scoring.engine import scoring_engine
from src.scoring.momentum import momentum_scorer
from src.storage.models import ChainProduct, EvidenceEvent, Organization


def test_confidence_and_momentum_calculation():
    org = Organization(org_id="org1", display_name="Kora Labs", official_domains=["kora.network"], github_orgs=["kora-network"])
    chain = ChainProduct(
        id="cand1",
        organization_id="org1",
        canonical_name="Kora Network",
        slug="kora-network",
        stage=LifecycleStage.S2_PUBLIC_TESTNET.value,
        first_seen_at=datetime.now(timezone.utc),
        registry_pr_opened_at=datetime.now(timezone.utc),
    )
    chain.organization = org

    ev1 = EvidenceEvent(
        source_id="ethereum_lists",
        external_id="ev1",
        url="http://github.com",
        source_family="registry",
        observed_at=datetime.now(timezone.utc),
        content_hash="h1",
    )
    ev2 = EvidenceEvent(
        source_id="rss_sitemaps",
        external_id="ev2",
        url="http://kora.network/blog",
        source_family="web",
        observed_at=datetime.now(timezone.utc),
        content_hash="h2",
    )

    conf, c_breakdown = confidence_scorer.calculate(chain, [ev1, ev2], has_technical_fingerprint=True)
    assert conf >= 65.0

    mom, m_breakdown = momentum_scorer.calculate(chain, [ev1, ev2])
    assert mom >= 40.0


def test_outreach_gate_promotion_to_hot():
    org = Organization(org_id="org1", display_name="Kora Labs", official_domains=["kora.network"], github_orgs=["kora-network"])
    chain = ChainProduct(
        id="cand1",
        organization_id="org1",
        canonical_name="Kora Network",
        slug="kora-network",
        stage=LifecycleStage.S2_PUBLIC_TESTNET.value,
        first_seen_at=datetime.now(timezone.utc),
        registry_pr_opened_at=datetime.now(timezone.utc),
        last_verified_at=datetime.now(timezone.utc),
    )
    chain.organization = org

    ev1 = EvidenceEvent(source_id="ethereum_lists", external_id="1", url="http://gh.com", source_family="registry", observed_at=datetime.now(timezone.utc), content_hash="h1")
    ev2 = EvidenceEvent(source_id="rss_sitemaps", external_id="2", url="http://kora.com", source_family="web", observed_at=datetime.now(timezone.utc), content_hash="h2")

    res = scoring_engine.evaluate(
        chain=chain,
        evidence_events=[ev1, ev2],
        africa_fit=85.0, # High Africa Fit
        risk=10.0,       # Low Risk
        has_technical_fingerprint=True,
    )

    assert res.outreach_gate_passed is True
    assert res.outreach_score >= 70.0
    assert res.state == CandidateState.HOT
