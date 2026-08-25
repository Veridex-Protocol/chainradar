"""Momentum (M: 0..100) scoring component."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from src.storage.models import ChainProduct, EvidenceEvent


class MomentumScorer:
    """Calculates development and public engagement momentum (M: 0..100)."""

    @staticmethod
    def calculate(chain: ChainProduct, evidence_events: List[EvidenceEvent]) -> Tuple[float, Dict[str, float]]:
        breakdown: Dict[str, float] = {}
        now = datetime.now(timezone.utc)

        # 1. Event velocity (recent signals count)
        recent_events = [e for e in evidence_events if now - e.observed_at <= timedelta(days=14)]
        velocity_score = min(35.0, len(recent_events) * 7.0)
        breakdown["event_velocity"] = velocity_score

        # 2. Stage momentum
        stage_score = 10.0
        if chain.stage in ("S2_public_testnet", "S3_incentivized_testnet"):
            stage_score = 30.0
        elif chain.stage == "S4_mainnet_announced":
            stage_score = 35.0
        elif chain.stage == "S5_early_mainnet":
            stage_score = 25.0
        breakdown["stage_momentum"] = stage_score

        # 3. Multi-source activity
        sources_seen = {e.source_id for e in recent_events}
        multi_source_score = min(20.0, len(sources_seen) * 5.0)
        breakdown["multi_source_activity"] = multi_source_score

        # 4. Opportunity & hiring signals
        hiring_or_grants = any(e.source_family in ("careers", "social") for e in recent_events)
        opp_score = 15.0 if hiring_or_grants else 5.0
        breakdown["commercial_signals"] = opp_score

        total_momentum = min(100.0, sum(breakdown.values()))
        return total_momentum, breakdown


momentum_scorer = MomentumScorer()
