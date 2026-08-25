"""Temporal backtesting and score calibration (spec 24).

The point of a backtest here is to measure how *early* and how *accurately* the
engine finds chains. That only means something if the replay drives the real
scoring path: a runner that assigns its own confidence numbers is measuring its
own fixtures, not the engine.

So each fixture is replayed as evidence events with timestamps, filtered to the
cutoff, and pushed through the same `scoring_engine` and `africa_classifier`
the live pipeline uses. No evidence dated after the cutoff is visible to the
scorer, which is what keeps later knowledge from leaking into features.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.classifiers.africa import africa_classifier
from src.core.types import CandidateState
from src.scoring.engine import scoring_engine
from src.storage.models import ChainProduct, EvidenceEvent, Network, NetworkIncarnation, Organization, ScoreSnapshot
from src.util.timeutil import parse_iso, to_utc, utcnow

logger = logging.getLogger(__name__)

# States that count as the engine having surfaced a candidate for action.
PROMOTED_STATES = {CandidateState.HOT, CandidateState.QUALIFIED}


@dataclass
class ReplayResult:
    """One fixture scored as of a cutoff."""

    name: str
    is_positive: bool
    state: CandidateState
    confidence: float
    outreach_score: float
    radar_score: float
    africa_label: str
    africa_score: float
    gate_passed: bool
    lead_time_days: Optional[float] = None
    gate_failures: List[str] = field(default_factory=list)

    @property
    def promoted(self) -> bool:
        return self.state in PROMOTED_STATES


def _build_chain(fixture: Dict[str, Any], visible_events: Sequence[EvidenceEvent]) -> ChainProduct:
    """Assemble the in-memory candidate the scorer would have seen."""
    chain = ChainProduct(
        id=f"bt-{fixture['name']}",
        canonical_name=fixture["name"],
        slug=fixture["name"].lower(),
        stage=fixture.get("stage", "S0_research_hint"),
        first_seen_at=min((e.observed_at for e in visible_events), default=utcnow()),
    )

    domains = fixture.get("official_domains") or []
    github = fixture.get("github_orgs") or []
    if domains or github:
        chain.organization = Organization(
            org_id=f"bt-org-{fixture['name']}",
            display_name=fixture["name"],
            official_domains=list(domains),
            github_orgs=list(github),
        )
    else:
        chain.organization = None

    chain_id = fixture.get("chain_id")
    if chain_id:
        network = Network(
            id=f"bt-net-{fixture['name']}",
            chain_product_id=chain.id,
            environment="testnet",
            protocol_namespace="eip155",
            human_chain_id=chain_id,
            caip2=f"eip155:{chain_id}",
            rpc_urls=[f"https://rpc.{fixture['name'].lower()}.invalid"],
        )
        if fixture.get("verified_genesis"):
            network.incarnations = [
                NetworkIncarnation(
                    id=f"bt-inc-{fixture['name']}",
                    network_id=network.id,
                    genesis_fingerprint=f"0xgenesis-{fixture['name']}",
                    last_verified_at=max(e.observed_at for e in visible_events),
                    status="active",
                )
            ]
        else:
            network.incarnations = []
        chain.networks = [network]
    else:
        chain.networks = []

    if fixture.get("stage") in ("S4_mainnet_announced",):
        chain.mainnet_announced_for = parse_iso(fixture.get("mainnet_live_at"))
    return chain


def _visible_events(
    fixture: Dict[str, Any],
    cutoff: datetime,
    excluded_families: Set[str],
) -> List[EvidenceEvent]:
    """Evidence dated at or before the cutoff, minus any ablated families."""
    signal_at = parse_iso(fixture["first_eligible_signal"])
    if signal_at is None:
        return []

    events: List[EvidenceEvent] = []
    for family, day_offset in fixture.get("events", [("registry", 0)]):
        if family in excluded_families:
            continue
        observed_at = signal_at + timedelta(days=day_offset)
        if observed_at > cutoff:
            continue
        events.append(
            EvidenceEvent(
                source_id=f"{family}_source",
                external_id=f"{fixture['name']}-{family}-{day_offset}",
                url=f"https://evidence.invalid/{fixture['name']}/{family}",
                source_family=family,
                observed_at=observed_at,
                content_hash=f"{fixture['name']}-{family}-{day_offset}",
            )
        )
    return events


class TemporalBacktestRunner:
    """Replays fixtures against the real scorer at a point in time."""

    def __init__(
        self,
        positive_fixtures: List[Dict[str, Any]],
        negative_fixtures: List[Dict[str, Any]],
    ) -> None:
        self.positive_fixtures = positive_fixtures
        self.negative_fixtures = negative_fixtures

    # ------------------------------------------------------------------
    def _replay_one(
        self,
        fixture: Dict[str, Any],
        *,
        is_positive: bool,
        cutoff: datetime,
        excluded_families: Set[str],
    ) -> Optional[ReplayResult]:
        events = _visible_events(fixture, cutoff, excluded_families)
        if not events:
            # Nothing was public yet at this cutoff, so the engine cannot be
            # credited or blamed for this fixture.
            return None

        chain = _build_chain(fixture, events)
        text = fixture.get("sample_text", "")

        # Only a Tier A family constitutes an official, project-origin source.
        is_official = any(e.source_family in ("registry", "official_web") for e in events)
        has_activity = any(
            e.source_family in ("code_search", "careers", "official_web", "registry") for e in events
        )
        vector, label = africa_classifier.evaluate_feature_vector(
            text,
            is_official_source=is_official,
            has_public_contact=True if fixture.get("official_domains") else None,
            has_funding_or_activity=True if has_activity else None,
        )

        verified = bool(fixture.get("verified_genesis")) and bool(fixture.get("chain_id"))
        token_only = bool(fixture.get("is_token_only")) and not fixture.get("chain_id")

        result = scoring_engine.evaluate(
            chain=chain,
            evidence_events=events,
            africa_fit=vector.total_score,
            risk=0.0,
            has_technical_fingerprint=verified,
            has_advancing_liveness=verified,
            africa_label=label.value,
            is_hard_blocked=token_only,
            # Score as of the cutoff, so freshness and staleness are judged at
            # the moment being replayed rather than today.
            now=cutoff,
        )

        lead_time = None
        mainnet_at = parse_iso(fixture.get("mainnet_live_at"))
        first_seen = min(e.observed_at for e in events)
        if mainnet_at:
            lead_time = (to_utc(mainnet_at) - to_utc(first_seen)).total_seconds() / 86400.0

        return ReplayResult(
            name=fixture["name"],
            is_positive=is_positive,
            state=result.state,
            confidence=result.confidence,
            outreach_score=result.outreach_score,
            radar_score=result.radar_score,
            africa_label=label.value,
            africa_score=vector.total_score,
            gate_passed=result.outreach_gate_passed,
            lead_time_days=lead_time,
            gate_failures=result.gate_failures,
        )

    def replay(
        self, evaluation_cutoff: datetime, excluded_families: Optional[Set[str]] = None
    ) -> List[ReplayResult]:
        excluded = excluded_families or set()
        results: List[ReplayResult] = []
        for fixture in self.positive_fixtures:
            outcome = self._replay_one(
                fixture, is_positive=True, cutoff=evaluation_cutoff, excluded_families=excluded
            )
            if outcome:
                results.append(outcome)
        for fixture in self.negative_fixtures:
            outcome = self._replay_one(
                fixture, is_positive=False, cutoff=evaluation_cutoff, excluded_families=excluded
            )
            if outcome:
                results.append(outcome)
        return results

    # ------------------------------------------------------------------
    def run_backtest(
        self, evaluation_cutoff: datetime, excluded_families: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Score every visible fixture and compute the spec-24 metrics."""
        results = self.replay(evaluation_cutoff, excluded_families)
        positives = [r for r in results if r.is_positive]
        negatives = [r for r in results if not r.is_positive]

        # Precision@20 is measured on the Radar ranking, which is what an
        # analyst actually reads down (spec 24).
        ranked = sorted(results, key=lambda r: r.radar_score, reverse=True)
        top_20 = ranked[:20]
        precision_at_20 = (
            sum(1 for r in top_20 if r.is_positive) / len(top_20) if top_20 else 1.0
        )

        promoted_negatives = [r for r in negatives if r.promoted]
        false_promotion_rate = len(promoted_negatives) / len(negatives) if negatives else 0.0

        # Africa precision: of the fixtures we labelled A1/A2, how many were
        # genuinely explicit? A3 is a hypothesis and is excluded by design.
        africa_labeled = [r for r in positives if r.africa_label.startswith(("A1", "A2"))]
        africa_correct = 0
        expected_by_name = {
            f["name"]: f.get("expected_africa_label", "A4_no_evidence")
            for f in self.positive_fixtures
        }
        for r in africa_labeled:
            if expected_by_name.get(r.name, "").startswith(("A1", "A2")):
                africa_correct += 1
        africa_intent_precision = (
            africa_correct / len(africa_labeled) if africa_labeled else 1.0
        )

        lead_times = [r.lead_time_days for r in positives if r.lead_time_days is not None]
        recalled = [r for r in positives if r.promoted]

        return {
            "evaluation_cutoff": evaluation_cutoff.isoformat(),
            "excluded_families": sorted(excluded_families or []),
            "total_evaluated": len(results),
            "detected_positives": len(positives),
            "promoted_positives": len(recalled),
            "positive_recall": round(len(recalled) / len(positives), 4) if positives else 0.0,
            "false_promotions": len(promoted_negatives),
            "false_promotion_rate": round(false_promotion_rate, 4),
            "precision_at_20": round(precision_at_20, 4),
            "africa_intent_precision": round(africa_intent_precision, 4),
            "median_lead_time_days": round(median(lead_times), 2) if lead_times else None,
            "top_candidates": [
                {
                    "name": r.name,
                    "is_positive": r.is_positive,
                    "state": r.state.value,
                    "radar_score": r.radar_score,
                    "outreach_score": r.outreach_score,
                    "confidence": r.confidence,
                    "africa_label": r.africa_label,
                }
                for r in top_20
            ],
        }

    def run_cutoff_sweep(
        self,
        start: datetime,
        end: datetime,
        step_days: int = 1,
    ) -> Dict[str, Any]:
        """Score daily snapshots across a window and record first detection.

        A single far-future cutoff cannot measure recall: by then every
        fixture's evidence has aged past its stage TTL and the engine
        correctly reports STALE. Time-to-discovery is only meaningful as a
        sweep, which is why spec 24 asks for daily snapshots.
        """
        first_promoted: Dict[str, datetime] = {}
        first_seen: Dict[str, datetime] = {}
        per_cutoff: List[Dict[str, Any]] = []

        cutoff = start
        while cutoff <= end:
            results = self.replay(cutoff)
            promoted = 0
            for r in results:
                if r.name not in first_seen:
                    first_seen[r.name] = cutoff
                if r.promoted:
                    promoted += 1
                    if r.name not in first_promoted:
                        first_promoted[r.name] = cutoff
            per_cutoff.append(
                {
                    "cutoff": cutoff.isoformat(),
                    "evaluated": len(results),
                    "promoted": promoted,
                }
            )
            cutoff += timedelta(days=step_days)

        positive_names = {f["name"] for f in self.positive_fixtures}
        negative_names = {f["name"] for f in self.negative_fixtures}

        detected_positives = positive_names & first_promoted.keys()
        detected_negatives = negative_names & first_promoted.keys()

        # Time-to-discovery: days from the first public signal to the first
        # cutoff at which the engine promoted the candidate.
        discovery_lags: List[float] = []
        for fixture in self.positive_fixtures:
            promoted_at = first_promoted.get(fixture["name"])
            signal_at = parse_iso(fixture["first_eligible_signal"])
            if promoted_at and signal_at:
                discovery_lags.append((to_utc(promoted_at) - to_utc(signal_at)).days)

        # Lead time relative to mainnet: positive means we found it first.
        mainnet_leads: List[float] = []
        for fixture in self.positive_fixtures:
            promoted_at = first_promoted.get(fixture["name"])
            mainnet_at = parse_iso(fixture.get("mainnet_live_at"))
            if promoted_at and mainnet_at:
                mainnet_leads.append((to_utc(mainnet_at) - to_utc(promoted_at)).days)

        return {
            "window": {"start": start.isoformat(), "end": end.isoformat(), "step_days": step_days},
            "positive_recall": round(len(detected_positives) / len(positive_names), 4)
            if positive_names
            else 0.0,
            "false_promotion_rate": round(len(detected_negatives) / len(negative_names), 4)
            if negative_names
            else 0.0,
            "median_time_to_discovery_days": round(median(discovery_lags), 2)
            if discovery_lags
            else None,
            "p90_time_to_discovery_days": round(
                sorted(discovery_lags)[int(0.9 * (len(discovery_lags) - 1))], 2
            )
            if discovery_lags
            else None,
            "median_lead_time_before_mainnet_days": round(median(mainnet_leads), 2)
            if mainnet_leads
            else None,
            "per_cutoff": per_cutoff,
        }

    def run_source_ablation(self, evaluation_cutoff: datetime) -> Dict[str, Any]:
        """Quantify each source family's unique contribution (spec 24).

        Removing a family and re-measuring recall answers the question the
        spec actually cares about commercially: which feeds are worth paying
        for, and which are redundant with what we already have.
        """
        baseline = self.run_backtest(evaluation_cutoff)
        families: Set[str] = set()
        for fixture in list(self.positive_fixtures) + list(self.negative_fixtures):
            for family, _offset in fixture.get("events", []):
                families.add(family)

        ablations: Dict[str, Any] = {}
        for family in sorted(families):
            without = self.run_backtest(evaluation_cutoff, excluded_families={family})
            ablations[family] = {
                "recall_without": without["positive_recall"],
                "recall_delta": round(
                    baseline["positive_recall"] - without["positive_recall"], 4
                ),
                "precision_at_20_without": without["precision_at_20"],
                "detected_positives_without": without["detected_positives"],
            }

        return {
            "baseline": {
                "positive_recall": baseline["positive_recall"],
                "precision_at_20": baseline["precision_at_20"],
            },
            "ablations": ablations,
            # A family whose removal costs recall is carrying unique signal.
            "unique_contributors": sorted(
                (f for f, m in ablations.items() if m["recall_delta"] > 0),
                key=lambda f: ablations[f]["recall_delta"],
                reverse=True,
            ),
        }


async def build_calibration_report(session: AsyncSession) -> Dict[str, Any]:
    """Weekly precision / miss / drift report from live score history (spec 18).

    Reads the snapshot ledger rather than current state, which is only possible
    because snapshots are appended rather than overwritten.
    """
    now = utcnow()
    week_ago = now - timedelta(days=7)

    state_counts_stmt = (
        select(ScoreSnapshot.state, func.count())
        .where(ScoreSnapshot.calculated_at >= week_ago)
        .group_by(ScoreSnapshot.state)
    )
    state_counts = {state: count for state, count in (await session.execute(state_counts_stmt)).all()}

    version_stmt = (
        select(ScoreSnapshot.rule_version, func.count())
        .where(ScoreSnapshot.calculated_at >= week_ago)
        .group_by(ScoreSnapshot.rule_version)
    )
    versions = {v: c for v, c in (await session.execute(version_stmt)).all()}

    avg_stmt = select(
        func.avg(ScoreSnapshot.confidence),
        func.avg(ScoreSnapshot.outreach_score),
        func.avg(ScoreSnapshot.risk),
    ).where(ScoreSnapshot.calculated_at >= week_ago)
    avg_confidence, avg_outreach, avg_risk = (await session.execute(avg_stmt)).one()

    total = sum(state_counts.values())
    return {
        "generated_at": now.isoformat(),
        "window_days": 7,
        "snapshots": total,
        "state_counts": state_counts,
        # More than one rule version in the window means a config change landed;
        # score movement in that period may be a rule change, not the market.
        "rule_versions": versions,
        "config_changed_during_window": len(versions) > 1,
        "averages": {
            "confidence": round(float(avg_confidence or 0.0), 2),
            "outreach_score": round(float(avg_outreach or 0.0), 2),
            "risk": round(float(avg_risk or 0.0), 2),
        },
        "summary": (
            f"{total} snapshots across {len(state_counts)} states; "
            f"{len(versions)} rule version(s) in play."
        ),
    }
