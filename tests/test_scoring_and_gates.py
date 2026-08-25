"""Confidence, momentum, risk, the outreach gate and the state machine (spec 17)."""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.types import CandidateState, LifecycleStage
from src.scoring.confidence import confidence_scorer, evaluate_attribution, freshness_score
from src.scoring.engine import is_stale, scoring_engine
from src.scoring.momentum import momentum_scorer
from src.storage.models import (
    ChainProduct,
    EvidenceEvent,
    Network,
    NetworkIncarnation,
    Organization,
)

NOW = datetime.now(timezone.utc)


def _evidence(source_id: str, family: str, observed_at: datetime | None = None) -> EvidenceEvent:
    return EvidenceEvent(
        source_id=source_id,
        external_id=f"{source_id}-{family}",
        url=f"https://example.invalid/{source_id}",
        source_family=family,
        observed_at=observed_at or NOW,
        content_hash=f"hash-{source_id}-{family}",
    )


def _attributed_org() -> Organization:
    return Organization(
        org_id="org1",
        display_name="Kora Labs",
        official_domains=["kora.network"],
        github_orgs=["kora-network"],
    )


def _verified_chain(**overrides) -> ChainProduct:
    """A candidate that is genuinely verified: genesis recorded and re-checked."""
    chain = ChainProduct(
        id="cand1",
        organization_id="org1",
        canonical_name="Kora Network",
        slug="kora-network",
        first_seen_at=NOW,
        registry_pr_opened_at=NOW,
        last_verified_at=NOW,
        **{"stage": LifecycleStage.S2_PUBLIC_TESTNET.value, **overrides},
    )
    chain.organization = _attributed_org()
    network = Network(
        id="net1",
        chain_product_id="cand1",
        environment="testnet",
        caip2="eip155:987654",
        protocol_namespace="eip155",
        human_chain_id="987654",
        rpc_urls=["https://rpc.kora.network"],
    )
    network.incarnations = [
        NetworkIncarnation(
            id="inc1",
            network_id="net1",
            genesis_fingerprint="0xgenesis",
            last_verified_at=NOW,
            status="active",
        )
    ]
    chain.networks = [network]
    return chain


def test_confidence_and_momentum_calculation():
    chain = _verified_chain()
    evidence = [_evidence("ethereum_lists", "registry"), _evidence("rss_sitemaps", "official_web")]

    conf, breakdown = confidence_scorer.calculate(
        chain, evidence, has_technical_fingerprint=True, has_advancing_liveness=True
    )
    assert conf >= 65.0
    assert breakdown["official_attribution"] == 20.0
    assert breakdown["technical_fingerprint"] == 25.0

    mom, _ = momentum_scorer.calculate(chain, evidence)
    assert mom >= 40.0


def test_outreach_gate_promotion_to_hot():
    chain = _verified_chain()
    result = scoring_engine.evaluate(
        chain=chain,
        evidence_events=[_evidence("ethereum_lists", "registry"), _evidence("rss", "official_web")],
        africa_fit=85.0,
        risk=10.0,
        has_technical_fingerprint=True,
        has_advancing_liveness=True,
        africa_label="A1_explicit_intent",
    )
    assert result.outreach_gate_passed is True
    assert result.outreach_score >= 70.0
    assert result.state == CandidateState.HOT


def test_full_technical_fingerprint_requires_genesis_and_liveness():
    """25/25 means identity *and* genesis *and* advancing state (spec 17)."""
    chain = _verified_chain()
    _, verified = confidence_scorer.calculate(
        chain, [_evidence("r", "registry")], has_technical_fingerprint=True, has_advancing_liveness=True
    )
    assert verified["technical_fingerprint"] == 25.0

    # An endpoint that answered once, with no genesis on record, is worth less.
    bare = ChainProduct(
        id="c2", canonical_name="Bare", slug="bare", stage=LifecycleStage.S2_PUBLIC_TESTNET.value,
        first_seen_at=NOW,
    )
    bare.organization = _attributed_org()
    bare.networks = []
    _, unverified = confidence_scorer.calculate(
        bare, [_evidence("r", "registry")], has_technical_fingerprint=True
    )
    assert unverified["technical_fingerprint"] == 15.0


def test_gate_blocks_candidate_without_official_attribution():
    """An auto-created organization row is not official attribution.

    The resolver mints an organization for every candidate from its own name,
    so the gate must look for a real external anchor - domain, repository or
    verified handle - not merely the presence of an organization.
    """
    chain = _verified_chain()
    chain.organization = Organization(
        org_id="org-nameonly", display_name="Anon Chain",
        official_domains=[], github_orgs=[], social_handles={},
    )

    facts = evaluate_attribution(chain, [])
    assert facts.is_officially_attributed is False

    result = scoring_engine.evaluate(
        chain=chain,
        evidence_events=[_evidence("a", "registry"), _evidence("b", "official_web")],
        africa_fit=90.0,
        risk=0.0,
        has_technical_fingerprint=True,
        has_advancing_liveness=True,
        africa_label="A1_explicit_intent",
    )
    assert result.outreach_gate_passed is False
    assert any("official attribution" in f.lower() for f in result.gate_failures)
    assert result.state is not CandidateState.HOT


def test_hot_requires_relevant_stage_or_explicit_africa_intent():
    """A strong score on a dormant research hint must not page an analyst."""
    chain = _verified_chain(stage=LifecycleStage.S0_RESEARCH_HINT.value)
    result = scoring_engine.evaluate(
        chain=chain,
        evidence_events=[_evidence("a", "registry"), _evidence("b", "official_web")],
        africa_fit=85.0,
        risk=5.0,
        has_technical_fingerprint=True,
        has_advancing_liveness=True,
        africa_label="A3_africa_compatible",  # inferred, not project-claimed
    )
    assert result.state != CandidateState.HOT

    # The same candidate with project-origin Africa intent does qualify.
    promoted = scoring_engine.evaluate(
        chain=chain,
        evidence_events=[_evidence("a", "registry"), _evidence("b", "official_web")],
        africa_fit=85.0,
        risk=5.0,
        has_technical_fingerprint=True,
        has_advancing_liveness=True,
        africa_label="A1_explicit_intent",
    )
    assert promoted.state == CandidateState.HOT


def test_stale_is_driven_by_stage_ttl_not_by_a_low_score():
    """STALE means the evidence aged out, not that the candidate scores badly."""
    chain = _verified_chain()  # S2 public testnet, TTL 21 days
    old = _evidence("ethereum_lists", "registry", observed_at=NOW - timedelta(days=40))

    stale, age, ttl = is_stale(chain, [old])
    assert stale is True and ttl == 21 and age > 21

    result = scoring_engine.evaluate(
        chain=chain, evidence_events=[old], africa_fit=85.0, risk=0.0,
        has_technical_fingerprint=True, has_advancing_liveness=True,
        africa_label="A1_explicit_intent",
    )
    assert result.state == CandidateState.STALE

    # A brand-new weak candidate is RADAR, never STALE.
    fresh_weak = ChainProduct(
        id="c3", canonical_name="Weak", slug="weak",
        stage=LifecycleStage.S0_RESEARCH_HINT.value, first_seen_at=NOW,
    )
    fresh_weak.organization = None
    fresh_weak.networks = []
    weak = scoring_engine.evaluate(chain=fresh_weak, evidence_events=[_evidence("s", "social")])
    assert weak.state == CandidateState.RADAR


def test_freshness_decays_per_signal_type():
    """A week-old tweet is stale; a week-old registry commit is not (spec 17)."""
    week_old = NOW - timedelta(days=7)
    social, _ = freshness_score([_evidence("x", "social", week_old)], now=NOW)
    registry, _ = freshness_score([_evidence("y", "registry", week_old)], now=NOW)
    assert social < registry
    # 7 days is ~2.3 social half-lives (3d) but only 1/3 of a registry one (21d).
    assert social < 2.5, f"week-old social should have decayed hard, got {social:.2f}"
    assert registry > 7.0, f"week-old registry evidence is still current, got {registry:.2f}"
    assert registry > social * 3


def test_rule_version_is_stamped_from_config():
    """Every score records the config version that produced it (spec 20)."""
    from src.config import settings

    result = scoring_engine.evaluate(chain=_verified_chain(), evidence_events=[_evidence("a", "registry")])
    assert result.rule_version == settings.RULE_VERSION
    assert result.rule_version.startswith("v1.0+")
