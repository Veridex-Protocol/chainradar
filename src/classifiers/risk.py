"""Risk penalty evaluator."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


class RiskEvaluator:
    """Evaluates risk penalties (R: 0..100, higher is worse) for a candidate chain."""

    @staticmethod
    def evaluate_risk(
        has_identity_mismatch: bool = False,
        has_chain_id_collision: bool = False,
        is_impersonation_or_unattributed: bool = False,
        is_token_only_or_content_farm: bool = False,
        is_copied_or_dormant_repo: bool = False,
        has_repeated_endpoint_failures: bool = False,
        has_security_warnings: bool = False,
    ) -> Tuple[float, Dict[str, float], List[str]]:
        """Calculates total risk penalty, breakdown, and warning flags."""
        breakdown: Dict[str, float] = {}
        flags: List[str] = []

        if has_identity_mismatch or has_chain_id_collision:
            penalty = 30.0
            breakdown["identity_collision_or_mismatch"] = penalty
            flags.append("Identity mismatch or unexplained chain-ID collision")

        if is_impersonation_or_unattributed:
            penalty = 25.0
            breakdown["no_official_attribution"] = penalty
            flags.append("No official attribution or possible impersonation")

        if is_token_only_or_content_farm:
            penalty = 25.0
            breakdown["token_only_or_content_farm"] = penalty
            flags.append("Only token-sale, referral or content-farm evidence")

        if is_copied_or_dormant_repo:
            penalty = 15.0
            breakdown["copied_or_dormant_repo"] = penalty
            flags.append("Copied or dormant repository / unverifiable binaries")

        if has_repeated_endpoint_failures:
            penalty = 10.0
            breakdown["repeated_endpoint_failures"] = penalty
            flags.append("Repeated endpoint/TLS/domain failures")

        if has_security_warnings:
            penalty = 15.0
            breakdown["security_warnings"] = penalty
            flags.append("Security warnings or opaque admin control")

        total_risk = min(100.0, sum(breakdown.values()))
        return total_risk, breakdown, flags


risk_evaluator = RiskEvaluator()
