"""Outreach fit: is this a chain worth approaching, and why? (spec 13, 22)

Discovery confidence says the chain is real. Africa fit says the market is
relevant. Neither answers the question an analyst actually has on a Monday
morning: *of the forty candidates in the queue, which five should I contact
this week, and what do I say?*

This assembles that answer from six things that independently change the
outcome of an approach:

1. **Vitality** — are they still building? A dormant project cannot be
   partnered with, whatever its scores. This is a gate, not a weight.
2. **Capacity** — did they publicly raise? A funded organization has budget and
   usually a stated mandate to spend it on ecosystem growth.
3. **Timing** — are they inside the outreach window? A pre-mainnet chain needs
   community and DevRel; an established one already has vendors.
4. **Reach** — audience size tells you whether they need distribution help or
   already have it.
5. **Africa relevance** — evidence-backed intent beats our own inference.
6. **Contactability** — a public business route that a human can actually use.

Every component is evidence-backed, and the rationale is written out in plain
language so the analyst can sanity-check the recommendation rather than trust
a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.classifiers.vitality import VitalityAssessment, VitalityStatus
from src.config import settings

# Fit tiers, in descending order of "reach out now".
TIER_PRIME = "prime"
TIER_STRONG = "strong"
TIER_WATCH = "watch"
TIER_NOT_READY = "not_ready"
TIER_DO_NOT_CONTACT = "do_not_contact"

# Stages where an outside partner can still shape the ecosystem.
_TIMING_SCORES = {
    "S2_public_testnet": 1.0,
    "S3_incentivized_testnet": 1.0,
    "S4_mainnet_announced": 0.95,
    "S5_early_mainnet": 0.85,
    "S1_devnet_prototype": 0.5,
    "S0_research_hint": 0.15,
    "S6_established_archived": 0.25,
}

_FUNDING_BAND_SCORES = {
    "well_funded": 1.0,
    "materially_funded": 0.8,
    "lightly_funded": 0.5,
    "raised_amount_undisclosed": 0.45,
    "no_public_funding_evidence": 0.2,
}


@dataclass
class OutreachFit:
    """A ranked, explainable recommendation."""

    score: float
    tier: str
    components: Dict[str, float] = field(default_factory=dict)
    rationale: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    recommended_action: str = ""
    suggested_angle: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "tier": self.tier,
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "rationale": self.rationale,
            "blockers": self.blockers,
            "recommended_action": self.recommended_action,
            "suggested_angle": self.suggested_angle,
        }


def audience_score(snapshots: Sequence[Any]) -> tuple[float, Dict[str, Any]]:
    """Normalize public audience counters into a 0-1 reach signal.

    Log-shaped on purpose: the difference between 200 and 2,000 followers says
    far more about a project's stage than the difference between 200,000 and
    2,000,000.
    """
    import math

    totals = {"followers": 0, "stars": 0, "contributors": 0}
    observed = False
    for snapshot in snapshots:
        for key in totals:
            value = getattr(snapshot, key, None)
            if value:
                totals[key] += int(value)
                observed = True

    if not observed:
        return 0.0, {"observed": False, **totals}

    followers = math.log10(totals["followers"] + 1) / 6.0     # ~1.0 at 1M
    stars = math.log10(totals["stars"] + 1) / 4.5             # ~1.0 at ~30k
    contributors = math.log10(totals["contributors"] + 1) / 2.5

    score = min(1.0, 0.5 * followers + 0.35 * stars + 0.15 * contributors)
    return score, {"observed": True, **totals}


class OutreachFitClassifier:
    """Combines vitality, capacity, timing, reach, relevance and contactability."""

    WEIGHTS = {
        "capacity": 0.22,
        "timing": 0.20,
        "africa_relevance": 0.25,
        "reach": 0.13,
        "contactability": 0.12,
        "engineering_activity": 0.08,
    }

    def assess(
        self,
        *,
        vitality: VitalityAssessment,
        funding_summary: Dict[str, Any],
        activity_snapshots: Sequence[Any],
        stage: Optional[str],
        africa_label: Optional[str],
        africa_fit: float,
        risk: float,
        has_public_contact: bool,
        outreach_gate_passed: bool,
        opportunity_types: Sequence[str] = (),
    ) -> OutreachFit:
        components: Dict[str, float] = {}
        rationale: List[str] = []
        blockers: List[str] = []

        # --- capacity ---------------------------------------------------
        band = funding_summary.get("band", "no_public_funding_evidence")
        components["capacity"] = _FUNDING_BAND_SCORES.get(band, 0.2)
        total = funding_summary.get("total_disclosed_usd")
        if total:
            rationale.append(
                f"Publicly raised ${total:,.0f} across "
                f"{funding_summary.get('rounds_with_disclosed_amount', 0)} disclosed round(s)"
                + (
                    f", most recently a {funding_summary['latest_round_type'].replace('_', ' ')}"
                    if funding_summary.get("latest_round_type")
                    else ""
                )
                + ". Budget and mandate are plausible."
            )
            investors = funding_summary.get("investors") or []
            if investors:
                rationale.append(f"Backed by {', '.join(investors[:4])}.")
        elif band == "raised_amount_undisclosed":
            rationale.append(
                "A funding round was announced without a figure; capacity is likely but unproven."
            )
        else:
            rationale.append(
                "No public funding evidence found. This is not evidence of being unfunded - "
                "many foundations never announce - but capacity cannot be assumed."
            )

        # --- timing -----------------------------------------------------
        components["timing"] = _TIMING_SCORES.get(stage or "", 0.3)
        if stage in ("S2_public_testnet", "S3_incentivized_testnet"):
            rationale.append(
                "In public testnet: the window where community, DevRel and validator "
                "programmes are still being decided."
            )
        elif stage == "S4_mainnet_announced":
            rationale.append(
                "Mainnet announced: launch-partner and go-to-market decisions are live now."
            )
        elif stage == "S5_early_mainnet":
            rationale.append("Early mainnet: adoption and user-acquisition needs are immediate.")
        elif stage == "S6_established_archived":
            rationale.append(
                "Past the early window; incumbent vendors are likely in place, so an "
                "approach needs a specialist angle."
            )

        # --- Africa relevance -------------------------------------------
        components["africa_relevance"] = min(1.0, max(0.0, africa_fit / 100.0))
        if africa_label == "A1_explicit_intent":
            rationale.append("Stated Africa intent from an official source - approach on their plan.")
            components["africa_relevance"] = min(1.0, components["africa_relevance"] + 0.15)
        elif africa_label == "A2_active_regional_motion":
            rationale.append("Already moving regionally - approach on execution, not persuasion.")
            components["africa_relevance"] = min(1.0, components["africa_relevance"] + 0.10)
        elif africa_label == "A3_africa_compatible":
            rationale.append(
                "Africa fit is our inference, not their stated plan. Any approach must be "
                "framed as a proposal, never as a response to something they announced."
            )
        elif africa_label == "A5_already_covered":
            rationale.append(
                "Local team or partners already in place - the opening is specialist support, "
                "not market entry."
            )

        # --- reach ------------------------------------------------------
        reach, audience = audience_score(activity_snapshots)
        components["reach"] = reach
        if audience.get("observed"):
            parts = [f"{k}={v:,}" for k, v in audience.items() if k != "observed" and v]
            if parts:
                rationale.append("Observed public audience: " + ", ".join(parts) + ".")
            if reach < 0.25:
                rationale.append(
                    "Small audience relative to peers, which usually means distribution "
                    "help is genuinely useful to them."
                )
        else:
            rationale.append("No audience metrics observed yet; reach is unknown, not zero.")

        # --- contactability ---------------------------------------------
        components["contactability"] = 1.0 if has_public_contact else 0.0
        if not has_public_contact:
            blockers.append("No public business contact route recorded.")

        # --- engineering activity ---------------------------------------
        github = next((s for s in activity_snapshots if s.channel == "github"), None)
        if github is not None:
            commits = github.commits_last_30d or 0
            releases = github.releases_last_90d or 0
            engineering = min(1.0, commits / 40.0 * 0.7 + min(releases, 5) / 5.0 * 0.3)
            components["engineering_activity"] = engineering
            if commits or releases:
                rationale.append(
                    f"Shipping: {commits} commit(s) in 30d, {releases} release(s) in 90d."
                )
            if github.extra_metrics.get("archived"):
                blockers.append("Primary repository is archived - the owner has declared it over.")
        else:
            components["engineering_activity"] = 0.0

        # --- gates ------------------------------------------------------
        if vitality.status == VitalityStatus.DEAD:
            blockers.append(
                f"No observed activity on any channel for over "
                f"{settings.VITALITY.thresholds_days['dormant']} days - treat as abandoned."
            )
        elif vitality.status == VitalityStatus.DORMANT:
            blockers.append("Dormant: no recent activity across the channels we can observe.")
        elif vitality.status == VitalityStatus.UNKNOWN:
            blockers.append("Vitality unknown - no channel has been successfully observed yet.")

        if not outreach_gate_passed:
            blockers.append("Outreach gate not passed (see gate_failures on the score).")
        if risk >= settings.ALERTS.hot.risk_max:
            blockers.append(f"Risk score {risk:.0f} is above the alerting ceiling.")

        raw = sum(self.WEIGHTS[k] * components.get(k, 0.0) for k in self.WEIGHTS)
        # Vitality scales the whole result rather than adding to it: no amount
        # of funding or reach makes a dead project worth contacting.
        score = 100.0 * raw * (vitality.score / 100.0 if vitality.score else 0.0)

        tier, action, angle = self._tier_for(
            score=score,
            blockers=blockers,
            vitality=vitality,
            africa_label=africa_label,
            opportunity_types=list(opportunity_types),
        )

        return OutreachFit(
            score=score,
            tier=tier,
            components=components,
            rationale=rationale,
            blockers=blockers,
            recommended_action=action,
            suggested_angle=angle,
        )

    @staticmethod
    def _tier_for(
        *,
        score: float,
        blockers: List[str],
        vitality: VitalityAssessment,
        africa_label: Optional[str],
        opportunity_types: List[str],
    ) -> tuple[str, str, Optional[str]]:
        angle = None
        if opportunity_types:
            angle = {
                "community_operations": "Community-as-a-service proposal",
                "developer_relations": "Developer onboarding and university/hub programme",
                "market_entry_bd": "Country launch and partnership map",
                "ambassador_grants": "Operate or recruit an Africa cohort",
                "validator_infrastructure": "Africa validator/RPC/infrastructure partnership",
                "adoption_user_acquisition": "Measured pilot with defined acquisition KPIs",
                "policy_enterprise": "Stakeholder engagement and compliant pilot",
                "investment_ma": "Route to qualified advisory; never infer sale intent",
            }.get(opportunity_types[0])

        if vitality.status in (VitalityStatus.DEAD,):
            return (
                TIER_DO_NOT_CONTACT,
                "No action. Archive with reason; re-open only on a new public signal.",
                None,
            )
        if blockers:
            return (
                TIER_NOT_READY,
                "Resolve the blockers before any approach: " + "; ".join(blockers[:2]),
                angle,
            )
        if score >= 65:
            return (
                TIER_PRIME,
                "Prepare a country brief and request an introduction this week.",
                angle,
            )
        if score >= 45:
            return (TIER_STRONG, "Prepare a tailored briefing for analyst approval.", angle)
        if score >= 25:
            return (TIER_WATCH, "Watch; collect more evidence before approaching.", angle)
        return (TIER_NOT_READY, "Insufficient basis for a credible approach.", angle)


outreach_fit_classifier = OutreachFitClassifier()
