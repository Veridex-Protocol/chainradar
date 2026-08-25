"""Scoring, ranking and alert-gate engine (spec 17).

Discovery confidence, commercial opportunity and risk stay separate and
explainable. Nothing here invents evidence: every component traces to an
evidence event, a verified fingerprint or an analyst override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from src.config import settings
from src.core.types import CandidateState, ScoreBreakdown
from src.scoring.confidence import (
    AttributionFacts,
    confidence_scorer,
    evaluate_attribution,
    independent_source_families,
)
from src.scoring.momentum import momentum_scorer
from src.storage.models import ChainProduct, EvidenceEvent
from src.util.timeutil import age_days, to_utc, utcnow

# Stages inside the primary outreach window (spec 02). Reaching HOT requires
# either one of these or explicit Africa intent, so a dormant research hint
# cannot page an analyst on score alone.
OUTREACH_WINDOW_STAGES = {
    "S2_public_testnet",
    "S3_incentivized_testnet",
    "S4_mainnet_announced",
    "S5_early_mainnet",
}

# Africa labels that count as project-origin intent rather than our own
# inference (spec 11: A3 is an Ashinity hypothesis, not a project claim).
EXPLICIT_AFRICA_LABELS = {"A1_explicit_intent", "A2_active_regional_motion"}


def clamp(val: float, min_v: float = 0.0, max_v: float = 100.0) -> float:
    return max(min_v, min(max_v, val))


def latest_evidence_at(evidence_events: Sequence[EvidenceEvent]) -> Optional[datetime]:
    times = [to_utc(e.observed_at) for e in evidence_events if e.observed_at]
    return max(times) if times else None


def is_stale(
    chain: ChainProduct,
    evidence_events: Sequence[EvidenceEvent],
    now: Optional[datetime] = None,
) -> Tuple[bool, Optional[float], Optional[int]]:
    """Has this candidate gone quiet past its stage-specific TTL? (spec 17)

    STALE is about *evidence age*, not about scoring low. A brand-new
    candidate with a weak score is RADAR; a once-strong candidate with no
    fresh evidence is STALE and needs re-verification.
    """
    now = now or utcnow()
    newest = latest_evidence_at(evidence_events)
    if newest is None:
        return True, None, None
    ttl_days = settings.STALENESS.days_by_stage.get(chain.stage or "S0_research_hint")
    if not ttl_days:
        return False, age_days(newest, now), None
    age = age_days(newest, now)
    return age > float(ttl_days), age, ttl_days


class ScoringEngine:
    """Calculates C, M, A, R; applies the outreach gate; sets candidate state."""

    @staticmethod
    def evaluate(
        chain: ChainProduct,
        evidence_events: List[EvidenceEvent],
        africa_fit: float = 0.0,
        risk: float = 0.0,
        risk_breakdown: Optional[Dict[str, float]] = None,
        has_technical_fingerprint: bool = False,
        has_advancing_liveness: bool = False,
        africa_label: Optional[str] = None,
        is_hard_blocked: bool = False,
        now: Optional[datetime] = None,
    ) -> ScoreBreakdown:
        now = now or utcnow()

        confidence, c_breakdown = confidence_scorer.calculate(
            chain=chain,
            evidence_events=evidence_events,
            has_technical_fingerprint=has_technical_fingerprint,
            has_advancing_liveness=has_advancing_liveness,
            now=now,
        )
        momentum, m_breakdown = momentum_scorer.calculate(chain=chain, evidence_events=evidence_events)

        w = settings.SCORE_WEIGHTS
        radar_score = clamp(
            w.radar_momentum * momentum + w.radar_confidence * confidence + w.radar_africa_fit * africa_fit
        )
        outreach_score = clamp(
            w.outreach_confidence * confidence
            + w.outreach_africa_fit * africa_fit
            + w.outreach_momentum * momentum
            - w.outreach_risk_penalty * risk
        )

        # ---- hard outreach gate (spec 01, 17) ----------------------------
        gate = settings.OUTREACH_GATE
        facts: AttributionFacts = evaluate_attribution(chain, evidence_events)
        families = independent_source_families(evidence_events)

        gate_failures: List[str] = []
        if confidence < gate.confidence_min:
            gate_failures.append(
                f"Confidence {confidence:.1f} below required {gate.confidence_min:.0f}"
            )
        if gate.require_official_attribution and not facts.is_officially_attributed:
            gate_failures.append(
                "No official attribution: " + facts.reasons[-1] if facts.reasons else
                "No official attribution"
            )
        corroborated = len(families) >= gate.min_independent_source_families
        if not (corroborated or (gate.allow_technical_verified_override and has_technical_fingerprint)):
            gate_failures.append(
                f"Needs technical verification or {gate.min_independent_source_families} independent "
                f"source families (have {len(families)}: {', '.join(sorted(families)) or 'none'})"
            )
        if is_hard_blocked:
            gate_failures.append("Hard blocked by policy (impersonation, token-only or manual reject)")

        outreach_gate_passed = not gate_failures

        # ---- state machine (spec 17) -------------------------------------
        alerts = settings.ALERTS
        stale, evidence_age, ttl_days = is_stale(chain, evidence_events, now=now)
        stage_relevant = (chain.stage or "") in OUTREACH_WINDOW_STAGES
        explicit_africa = (africa_label or "") in EXPLICIT_AFRICA_LABELS

        if is_hard_blocked:
            state = CandidateState.REJECT
        elif stale:
            # Applies regardless of score: the facts behind the score have
            # aged out and must be re-verified before anyone is contacted.
            state = CandidateState.STALE
        elif (
            outreach_gate_passed
            and confidence >= alerts.hot.confidence_min
            and outreach_score >= alerts.hot.priority_min
            and risk < alerts.hot.risk_max
            and (stage_relevant or explicit_africa)
        ):
            state = CandidateState.HOT
        elif (
            outreach_gate_passed
            and confidence >= alerts.qualified.confidence_min
            and outreach_score >= alerts.qualified.priority_min
        ):
            state = CandidateState.QUALIFIED
        else:
            state = CandidateState.RADAR

        if state == CandidateState.RADAR and radar_score < alerts.radar.radar_min:
            # Still RADAR, but below the watch threshold; the digest filters on
            # radar_min so it will not consume analyst attention.
            gate_failures.append(
                f"Radar {radar_score:.1f} below watch threshold {alerts.radar.radar_min:.0f}"
            )

        if stale and evidence_age is not None:
            gate_failures.append(
                f"No fresh evidence for {evidence_age:.1f}d"
                + (f" (stage TTL {ttl_days}d)" if ttl_days else "")
            )

        return ScoreBreakdown(
            confidence=round(confidence, 2),
            confidence_breakdown={k: round(float(v), 3) for k, v in c_breakdown.items()},
            momentum=round(momentum, 2),
            momentum_breakdown={k: round(float(v), 3) for k, v in m_breakdown.items()},
            africa_fit=round(africa_fit, 2),
            risk=round(risk, 2),
            risk_breakdown=risk_breakdown or {},
            radar_score=round(radar_score, 2),
            outreach_score=round(outreach_score, 2),
            outreach_gate_passed=outreach_gate_passed,
            gate_failures=gate_failures,
            state=state,
            calculated_at=now,
            rule_version=settings.RULE_VERSION,
        )


scoring_engine = ScoringEngine()
