"""Discovery Confidence (C: 0..100) and official-attribution facts (spec 17)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.config import settings
from src.storage.models import ChainProduct, EvidenceEvent
from src.util.timeutil import age_days, to_utc

# Source families that constitute an independent origin. Reposts, mirrors and
# syndications of one press release are one origin (spec 05 promotion policy),
# which is why corroboration counts *families*, never raw event volume.
_INDEPENDENT_FAMILIES_EXCLUDED = {"unknown", ""}


@dataclass
class AttributionFacts:
    """Why (or why not) a candidate counts as officially attributed.

    Kept separate from the score so the outreach gate can consult the *fact*
    rather than inferring it from a score component, and so an analyst can see
    which specific link was missing.
    """

    has_official_domain: bool = False
    has_official_repo: bool = False
    has_official_social: bool = False
    has_registry_record: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def is_officially_attributed(self) -> bool:
        """An organization/domain/repository relationship, per the hard gate.

        Merely having an organization row is not attribution: the resolver
        creates one for every candidate from its own name. Attribution needs a
        real external anchor - a domain, a repository or a verified handle.
        """
        return self.has_official_domain or self.has_official_repo or self.has_official_social


def evaluate_attribution(
    chain: ChainProduct, evidence_events: Sequence[EvidenceEvent] = ()
) -> AttributionFacts:
    facts = AttributionFacts()
    org = getattr(chain, "organization", None)

    if org is not None:
        if getattr(org, "official_domains", None):
            facts.has_official_domain = True
            facts.reasons.append(f"official domain(s): {', '.join(list(org.official_domains)[:3])}")
        if getattr(org, "github_orgs", None):
            facts.has_official_repo = True
            facts.reasons.append(f"github org(s): {', '.join(list(org.github_orgs)[:3])}")
        if getattr(org, "social_handles", None):
            facts.has_official_social = True
            facts.reasons.append("verified official social handle")

    if chain.registry_pr_opened_at or chain.registry_merged_at:
        facts.has_registry_record = True
        facts.reasons.append("registry submission recorded")

    if not facts.is_officially_attributed:
        facts.reasons.append(
            "no official domain, repository or verified handle links this network to an organization"
        )
    return facts


def independent_source_families(evidence_events: Sequence[EvidenceEvent]) -> Set[str]:
    return {
        e.source_family
        for e in evidence_events
        if e.source_family and e.source_family not in _INDEPENDENT_FAMILIES_EXCLUDED
    }


def freshness_score(
    evidence_events: Sequence[EvidenceEvent], now: Optional[datetime] = None, cap: float = 10.0
) -> Tuple[float, Dict[str, float]]:
    """Freshness with per-signal-type decay (spec 17).

    A social post and a registry commit age at very different rates: a
    three-day-old tweet says little, a three-day-old registry commit is still
    current. Each event decays on its family's half-life and the freshest
    contribution wins, so one stale family cannot drag down a live candidate.
    """
    now = now or datetime.now(timezone.utc)
    half_lives = settings.FRESHNESS.half_life_days
    default_half_life = half_lives.get("default", 14.0)

    best = 0.0
    per_family: Dict[str, float] = {}
    for event in evidence_events:
        if not event.observed_at:
            continue
        half_life = float(half_lives.get(event.source_family, default_half_life)) or default_half_life
        age = max(0.0, age_days(to_utc(event.observed_at), now))
        decayed = cap * (0.5 ** (age / half_life))
        family = event.source_family or "unknown"
        per_family[family] = max(per_family.get(family, 0.0), round(decayed, 3))
        best = max(best, decayed)
    return min(cap, best), per_family


class ConfidenceScorer:
    """Calculates Discovery Confidence (C: 0..100) from weighted evidence features."""

    @staticmethod
    def calculate(
        chain: ChainProduct,
        evidence_events: List[EvidenceEvent],
        has_technical_fingerprint: bool = False,
        has_advancing_liveness: bool = False,
        now: Optional[datetime] = None,
    ) -> Tuple[float, Dict[str, float]]:
        breakdown: Dict[str, float] = {}
        now = now or datetime.now(timezone.utc)

        # 1. Official attribution (0-20)
        facts = evaluate_attribution(chain, evidence_events)
        official_score = 0.0
        if facts.has_official_domain and facts.has_official_repo:
            official_score = 20.0
        elif facts.has_official_domain or facts.has_official_repo:
            official_score = 15.0
        elif facts.has_official_social:
            official_score = 8.0
        elif facts.has_registry_record:
            # A registry submission proves somebody attempted registration; it
            # is not proof of ownership on its own (spec 05).
            official_score = 4.0
        breakdown["official_attribution"] = official_score

        # 2. Registry / config evidence (0-15)
        registry_score = 0.0
        if chain.registry_merged_at:
            registry_score = 15.0
        elif chain.registry_pr_opened_at:
            registry_score = 10.0
        elif any(e.source_family == "registry" for e in evidence_events):
            registry_score = 8.0
        breakdown["registry_config_evidence"] = registry_score

        # 3. Technical fingerprint (0-25): identity, genesis and advancing state.
        tech_score = 0.0
        verified_genesis = any(
            inc.genesis_fingerprint and inc.last_verified_at
            for net in (chain.networks or [])
            for inc in (net.incarnations or [])
        )
        if has_advancing_liveness and verified_genesis:
            tech_score = 25.0
        elif has_technical_fingerprint and verified_genesis:
            tech_score = 20.0
        elif has_technical_fingerprint:
            tech_score = 15.0
        elif any(net.rpc_urls for net in (chain.networks or [])):
            # A published endpoint is a lead, not a fingerprint.
            tech_score = 6.0
        breakdown["technical_fingerprint"] = tech_score

        # 4. Independent corroboration (0-15)
        families = independent_source_families(evidence_events)
        corroboration_score = {0: 0.0, 1: 5.0, 2: 10.0}.get(len(families), 15.0)
        breakdown["independent_corroboration"] = corroboration_score

        # 5. Lifecycle evidence (0-15)
        lifecycle_score = 0.0
        if chain.mainnet_live_at:
            lifecycle_score = 15.0
        elif chain.mainnet_announced_for:
            lifecycle_score = 12.0
        elif chain.testnet_announced_at or any(
            net.environment == "testnet" for net in (chain.networks or [])
        ):
            lifecycle_score = 10.0
        elif chain.stage and chain.stage != "S0_research_hint":
            lifecycle_score = 6.0
        breakdown["lifecycle_evidence"] = lifecycle_score

        # 6. Freshness (0-10), decayed per signal type.
        fresh, per_family = freshness_score(evidence_events, now=now)
        breakdown["freshness"] = round(fresh, 2)

        total = sum(breakdown.values())
        return min(100.0, total), breakdown


confidence_scorer = ConfidenceScorer()
