"""Scoring, ranking, and alert gate engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from src.config import settings
from src.core.types import (
    CandidateState,
    LifecycleStage,
    ScoreBreakdown,
    WorkflowState,
)
from src.scoring.confidence import confidence_scorer
from src.scoring.momentum import momentum_scorer
from src.storage.models import ChainProduct, EvidenceEvent


def clamp(val: float, min_v: float = 0.0, max_v: float = 100.0) -> float:
    return max(min_v, min(max_v, val))


class ScoringEngine:
    """Calculates C, M, A, R scores, applies Outreach Gates, and sets candidate workflow state."""

    @staticmethod
    def evaluate(
        chain: ChainProduct,
        evidence_events: List[EvidenceEvent],
        africa_fit: float = 0.0,
        risk: float = 0.0,
        risk_breakdown: Optional[Dict[str, float]] = None,
        has_technical_fingerprint: bool = False,
        is_hard_blocked: bool = False,
    ) -> ScoreBreakdown:
        now = datetime.now(timezone.utc)

        # 1. Compute Confidence (C)
        confidence, c_breakdown = confidence_scorer.calculate(
            chain=chain,
            evidence_events=evidence_events,
            has_technical_fingerprint=has_technical_fingerprint,
        )

        # 2. Compute Momentum (M)
        momentum, m_breakdown = momentum_scorer.calculate(
            chain=chain,
            evidence_events=evidence_events,
        )

        # 3. Radar & Outreach Scores
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

        # 4. Outreach Gate Evaluation
        distinct_families = {e.source_family for e in evidence_events}
        has_official_attribution = bool(
            c_breakdown.get("official_attribution", 0.0) >= 10.0 or chain.organization_id or chain.registry_pr_opened_at
        )
        tech_or_multi_source = has_technical_fingerprint or (len(distinct_families) >= 2)

        gate_failures = []
        if confidence < settings.ALERTS.qualified.confidence_min:
            gate_failures.append(f"Confidence {confidence:.1f} < threshold {settings.ALERTS.qualified.confidence_min}")
        if not has_official_attribution:
            gate_failures.append("Missing official attribution or verified repository link")
        if not tech_or_multi_source:
            gate_failures.append("Lacks technical verification and has fewer than 2 independent source families")
        if is_hard_blocked:
            gate_failures.append("Hard blocked by policy / impersonation / token-only")

        outreach_gate_passed = len(gate_failures) == 0

        # 5. State Machine Transition
        state = CandidateState.RADAR
        if is_hard_blocked:
            state = CandidateState.REJECT
        elif (
            confidence >= settings.ALERTS.hot.confidence_min
            and outreach_score >= settings.ALERTS.hot.priority_min
            and risk < settings.ALERTS.hot.risk_max
            and outreach_gate_passed
        ):
            state = CandidateState.HOT
        elif (
            confidence >= settings.ALERTS.qualified.confidence_min
            and outreach_score >= settings.ALERTS.qualified.priority_min
            and outreach_gate_passed
        ):
            state = CandidateState.QUALIFIED
        elif radar_score < settings.ALERTS.radar.radar_min and not outreach_gate_passed:
            state = CandidateState.STALE

        return ScoreBreakdown(
            confidence=round(confidence, 2),
            confidence_breakdown=c_breakdown,
            momentum=round(momentum, 2),
            momentum_breakdown=m_breakdown,
            africa_fit=round(africa_fit, 2),
            risk=round(risk, 2),
            risk_breakdown=risk_breakdown or {},
            radar_score=round(radar_score, 2),
            outreach_score=round(outreach_score, 2),
            outreach_gate_passed=outreach_gate_passed,
            gate_failures=gate_failures,
            state=state,
            calculated_at=now,
            rule_version="v1.0",
        )


scoring_engine = ScoringEngine()
