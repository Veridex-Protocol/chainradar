"""Discovery Confidence (C: 0..100) scoring component."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Tuple
from src.storage.models import ChainProduct, EvidenceEvent


class ConfidenceScorer:
    """Calculates Discovery Confidence (C: 0..100) based on weighted evidence features."""

    @staticmethod
    def calculate(
        chain: ChainProduct,
        evidence_events: List[EvidenceEvent],
        has_technical_fingerprint: bool = False,
    ) -> Tuple[float, Dict[str, float]]:
        breakdown: Dict[str, float] = {}
        now = datetime.now(timezone.utc)

        # 1. Official Attribution (0-20)
        official_score = 0.0
        if chain.organization:
            if chain.organization.official_domains and chain.organization.github_orgs:
                official_score = 20.0
            elif chain.organization.official_domains or chain.organization.github_orgs:
                official_score = 15.0
            else:
                official_score = 8.0
        elif chain.repo_created_at or chain.registry_pr_opened_at:
            official_score = 10.0
        breakdown["official_attribution"] = official_score

        # 2. Registry / Config Evidence (0-15)
        registry_score = 0.0
        if chain.registry_merged_at:
            registry_score = 15.0
        elif chain.registry_pr_opened_at:
            registry_score = 10.0
        elif any(e.source_family == "registry" for e in evidence_events):
            registry_score = 8.0
        breakdown["registry_config_evidence"] = registry_score

        # 3. Technical Fingerprint (0-25)
        tech_score = 0.0
        if has_technical_fingerprint or chain.last_verified_at:
            tech_score = 25.0
        elif any(net.rpc_urls for net in chain.networks):
            tech_score = 12.0
        breakdown["technical_fingerprint"] = tech_score

        # 4. Independent Corroboration (0-15)
        distinct_families: Set[str] = {e.source_family for e in evidence_events}
        corroboration_score = 0.0
        if len(distinct_families) >= 3:
            corroboration_score = 15.0
        elif len(distinct_families) >= 2:
            corroboration_score = 10.0
        elif len(distinct_families) == 1:
            corroboration_score = 5.0
        breakdown["independent_corroboration"] = corroboration_score

        # 5. Lifecycle Evidence (0-15)
        lifecycle_score = 0.0
        if chain.mainnet_live_at:
            lifecycle_score = 15.0
        elif chain.mainnet_announced_for:
            lifecycle_score = 12.0
        elif chain.testnet_announced_at or any(net.environment == "testnet" for net in chain.networks):
            lifecycle_score = 10.0
        elif chain.stage != "S0_research_hint":
            lifecycle_score = 6.0
        breakdown["lifecycle_evidence"] = lifecycle_score

        # 6. Freshness (0-10)
        freshness_score = 0.0
        if evidence_events:
            most_recent = max(e.observed_at for e in evidence_events)
            if now - most_recent <= timedelta(days=7):
                freshness_score = 10.0
            elif now - most_recent <= timedelta(days=30):
                freshness_score = 6.0
            else:
                freshness_score = 2.0
        breakdown["freshness"] = freshness_score

        total_confidence = min(100.0, sum(breakdown.values()))
        return total_confidence, breakdown


confidence_scorer = ConfidenceScorer()
