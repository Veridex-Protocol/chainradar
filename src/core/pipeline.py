"""Intelligence pipeline: collect -> evidence -> resolve -> verify -> act (spec 03).

Ordering matters. Raw evidence is appended before anything derived is written,
classifiers never overwrite evidence, and scores are appended as snapshots
rather than mutated, so any decision can be replayed from the ledger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.alerting.evidence_card import EvidenceCardBuilder
from src.alerting.webhooks import webhook_dispatcher
from src.classifiers.africa import africa_classifier
from src.classifiers.opportunity import opportunity_classifier
from src.classifiers.risk import risk_evaluator
from src.collectors.base import Collector
from src.config import settings
from src.core.lifecycle import LifecycleManager
from src.core.resolver import EntityResolver
from src.core.types import (
    AfricaIntentLabel,
    CandidateState,
    Cursor,
    FetchBatch,
    RateBudget,
    RawItem,
    RawObservation,
)
from src.scoring.engine import scoring_engine
from src.storage.models import (
    AlertDispatch,
    ChainProduct,
    Contact,
    EvidenceEvent,
    Opportunity,
    ScoreSnapshot,
    Signal,
)
from src.storage.object_store import object_store
from src.storage.repository import Repository
from src.util.hashing_compat import stable_payload_hash
from src.util.redaction import channel_hash
from src.util.timeutil import to_utc, utcnow
from src.verifier.service import VerificationService

logger = logging.getLogger(__name__)

# Evidence families that demonstrate an organization is actually operating -
# shipping code, hiring, publishing. Used for the Africa vector's
# operating_capacity component, which must be observed rather than assumed.
_ACTIVITY_FAMILIES = {"code_search", "careers", "official_web", "registry", "infrastructure"}


class IntelligencePipeline:
    """End-to-end execution pipeline for early chain discovery."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = Repository(session)
        self.resolver = EntityResolver(session)
        self.verification = VerificationService(session)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------
    async def process_raw_item(self, collector: Collector, raw: RawItem) -> List[str]:
        """Ledger the raw item, resolve it, verify, rescore and alert."""
        content_hash, payload_path = object_store.store_payload(collector.source_id, raw.raw_payload)
        raw.content_hash = content_hash

        evidence = await self.repo.append_evidence(raw, raw_payload_path=payload_path)

        observations = collector.normalize(raw)
        affected: List[str] = []

        for obs in observations:
            candidate, is_new = await self.resolver.upsert_candidate(obs, evidence.id)
            affected.append(candidate.id)

            LifecycleManager.update_timestamps_from_claims(candidate, obs.claims)
            candidate.stage = LifecycleManager.compute_current_stage(
                candidate,
                networks=candidate.networks,
                has_incentive=bool(obs.claims.get("has_incentive")),
            ).value

            await self._extract_opportunities(candidate, obs, evidence)
            await self._extract_contacts(candidate, obs, evidence, raw)
            africa_label = await self._classify_africa(candidate, obs, collector, evidence)
            verification = await self._verify_candidate(candidate, obs)
            await self.rescore_candidate(
                candidate,
                africa_label=africa_label,
                verification=verification,
                trigger_alerts=True,
            )

        return affected

    # ------------------------------------------------------------------
    # Enrichment steps
    # ------------------------------------------------------------------
    async def _extract_opportunities(
        self, candidate: ChainProduct, obs: RawObservation, evidence: EvidenceEvent
    ) -> None:
        raw_text = obs.raw_text or ""
        if not raw_text:
            return
        for opp_type, response_suggestion, snippet in opportunity_classifier.classify(raw_text):
            stmt = select(Opportunity).where(
                Opportunity.candidate_id == candidate.id,
                Opportunity.opportunity_type == opp_type.value,
                Opportunity.active.is_(True),
            )
            existing = (await self.session.execute(stmt)).scalars().first()
            if existing:
                if evidence.id not in existing.evidence_refs:
                    existing.evidence_refs = list(existing.evidence_refs) + [evidence.id]
                continue
            self.session.add(
                Opportunity(
                    candidate_id=candidate.id,
                    opportunity_type=opp_type.value,
                    geography=", ".join(obs.claimed_locations) if obs.claimed_locations else None,
                    summary=f"{response_suggestion} (matched: {snippet})",
                    evidence_refs=[evidence.id],
                )
            )

    async def _extract_contacts(
        self,
        candidate: ChainProduct,
        obs: RawObservation,
        evidence: EvidenceEvent,
        raw: RawItem,
    ) -> None:
        """Record public business contacts, honouring suppression (spec 13, 23)."""
        for entry in obs.contacts:
            value = (entry.get("channel_value") or "").strip()
            if not value:
                continue
            if await self.repo.is_suppressed(value):
                # A suppressed channel must never re-enter outreach, even if a
                # source re-publishes it (acceptance test 16).
                continue
            digest = channel_hash(value)
            stmt = select(Contact).where(
                Contact.channel_hash == digest, Contact.org_id == candidate.organization_id
            )
            if (await self.session.execute(stmt)).scalars().first():
                continue
            self.session.add(
                Contact(
                    org_id=candidate.organization_id,
                    candidate_id=candidate.id,
                    role_type=entry.get("role_type", "business_contact"),
                    name=entry.get("name"),
                    channel_type=entry.get("channel_type", "form"),
                    channel_value=value,
                    channel_hash=digest,
                    permitted_purpose=entry.get("permitted_purpose", "partnership_inquiry"),
                    source_url=entry.get("source_url", raw.url),
                    suppressed=False,
                )
            )

    async def _classify_africa(
        self,
        candidate: ChainProduct,
        obs: RawObservation,
        collector: Collector,
        evidence: EvidenceEvent,
    ) -> Optional[str]:
        """Run the Africa classifier and persist the assessment."""
        raw_text = obs.raw_text or ""
        assessment = candidate.assessment
        if assessment is None:
            return None
        if assessment.analyst_override:
            # An analyst decision outranks the classifier until it expires.
            return assessment.intent_label

        # "Official" means the evidence came from the project itself: a Tier A
        # source family, not merely a high-reliability third party.
        is_official = getattr(collector, "tier", "") == "A" or evidence.source_family in (
            "registry",
            "official_web",
        )

        # Readiness inputs are passed only when actually observed; `None` means
        # "unknown" and scores zero rather than full marks.
        has_public_contact: Optional[bool] = None
        if obs.contacts:
            has_public_contact = True
        elif candidate.organization and candidate.organization.official_domains:
            has_public_contact = True

        evidence_events = await self.repo.list_evidence_for_candidate(candidate.id)
        families = {e.source_family for e in evidence_events} | {evidence.source_family}
        has_activity: Optional[bool] = True if families & _ACTIVITY_FAMILIES else None

        vector, label = africa_classifier.evaluate_feature_vector(
            raw_text,
            is_official_source=is_official,
            has_public_contact=has_public_contact,
            has_funding_or_activity=has_activity,
        )

        # Never downgrade a stronger, evidence-backed label on the basis of one
        # thin document; keep the strongest observed claim and its evidence.
        ranking = {
            AfricaIntentLabel.A4_NO_EVIDENCE.value: 0,
            AfricaIntentLabel.A3_AFRICA_COMPATIBLE.value: 1,
            AfricaIntentLabel.A2_ACTIVE_REGIONAL_MOTION.value: 2,
            AfricaIntentLabel.A1_EXPLICIT_INTENT.value: 3,
            AfricaIntentLabel.A5_ALREADY_COVERED.value: 4,
        }
        if ranking.get(label.value, 0) >= ranking.get(assessment.intent_label, 0):
            assessment.intent_label = label.value
            assessment.confidence = vector.confidence

        assessment.countries = sorted(set(list(assessment.countries) + vector.matched_countries))
        assessment.regions = sorted(set(list(assessment.regions) + vector.matched_regions))
        assessment.languages = sorted(set(list(assessment.languages) + vector.matched_languages))
        assessment.rails_use_cases = sorted(set(list(assessment.rails_use_cases) + vector.matched_rails))
        assessment.explicit_geo_score = max(assessment.explicit_geo_score, vector.explicit_geo)
        assessment.regional_action_score = max(assessment.regional_action_score, vector.regional_action)
        assessment.use_case_fit_score = max(assessment.use_case_fit_score, vector.use_case_fit)
        assessment.whitespace_score = max(assessment.whitespace_score, vector.whitespace)
        assessment.contactability_score = max(assessment.contactability_score, vector.contactability)
        assessment.operating_capacity_score = max(
            assessment.operating_capacity_score, vector.operating_capacity
        )
        assessment.total_score = min(
            100.0,
            assessment.explicit_geo_score
            + assessment.regional_action_score
            + assessment.use_case_fit_score
            + assessment.whitespace_score
            + assessment.contactability_score
            + assessment.operating_capacity_score,
        )
        if evidence.id not in assessment.evidence_ids:
            assessment.evidence_ids = list(assessment.evidence_ids) + [evidence.id]
        return assessment.intent_label

    async def _verify_candidate(
        self, candidate: ChainProduct, obs: RawObservation
    ) -> Dict[str, Any]:
        """Probe published endpoints read-only and record what was observed."""
        outcome: Dict[str, Any] = {
            "has_fingerprint": False,
            "has_advancing_liveness": False,
            "identity_mismatch": False,
            "endpoint_failures": 0,
        }
        if not settings.VERIFIER_ENABLED:
            return outcome

        if not settings.VERIFY_INLINE:
            # Verification is queued, not run inside the collector loop
            # (spec 19's processing loop enqueues `verify_candidate`).
            # Probing inline serializes an entire registry snapshot behind
            # thousands of RPC timeouts and holds the ingest transaction open
            # for the duration; the scheduler drains the queue instead.
            outcome["queued"] = True
            return outcome

        for network in candidate.networks or []:
            for endpoint in list(network.rpc_urls)[:2]:
                result, observation = await self.verification.probe_and_record(
                    endpoint,
                    family=candidate.stack_family,
                    candidate_id=candidate.id,
                    network_id=network.id,
                    expected_chain_id=network.human_chain_id,
                    probe_round=1,
                )
                if observation.failure_class == "identity_mismatch":
                    outcome["identity_mismatch"] = True
                    await self.resolver.open_review_task(
                        "identity_mismatch",
                        reason=observation.failure_detail or "Endpoint served a different chain ID",
                        candidate_id=candidate.id,
                        details={"endpoint": observation.endpoint},
                    )
                if not observation.success:
                    outcome["endpoint_failures"] += 1
                    continue

                outcome["has_fingerprint"] = True
                candidate.last_verified_at = result.checked_at
                await self.verification.apply_verified_identity(network, result)

                verdict = await self.verification.evaluate_liveness(endpoint)
                if verdict.live:
                    outcome["has_advancing_liveness"] = True
                outcome["liveness"] = verdict.as_evidence()
        return outcome

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------
    async def rescore_candidate(
        self,
        candidate: ChainProduct,
        *,
        africa_label: Optional[str] = None,
        verification: Optional[Dict[str, Any]] = None,
        trigger_alerts: bool = True,
    ) -> ScoreSnapshot:
        """Recompute scores and append a new snapshot (never overwrite one)."""
        verification = verification or {}
        evidence_events = await self.repo.list_evidence_for_candidate(candidate.id)

        signals = await self._active_signals(candidate.id)
        signal_types = {s.signal_type for s in signals}

        attribution_missing = not (
            candidate.organization
            and (candidate.organization.official_domains or candidate.organization.github_orgs)
        )
        token_only = self._looks_token_only(candidate)

        risk_score, risk_breakdown, risk_flags = risk_evaluator.evaluate_risk(
            has_identity_mismatch=bool(verification.get("identity_mismatch")),
            has_chain_id_collision="chain_id_collision" in signal_types
            or "genesis_changed" in signal_types,
            is_impersonation_or_unattributed=attribution_missing,
            is_token_only_or_content_farm=token_only,
            has_repeated_endpoint_failures=verification.get("endpoint_failures", 0) >= 2,
        )

        assessment = candidate.assessment
        result = scoring_engine.evaluate(
            chain=candidate,
            evidence_events=evidence_events,
            africa_fit=assessment.total_score if assessment else 0.0,
            risk=risk_score,
            risk_breakdown=risk_breakdown,
            has_technical_fingerprint=bool(
                verification.get("has_fingerprint") or candidate.last_verified_at
            ),
            has_advancing_liveness=bool(verification.get("has_advancing_liveness")),
            africa_label=africa_label or (assessment.intent_label if assessment else None),
            is_hard_blocked=token_only,
        )

        previous_state = candidate.score.state if candidate.score else None
        previous_workflow = candidate.score.workflow_state if candidate.score else "NEW"

        snapshot = ScoreSnapshot(
            candidate_id=candidate.id,
            confidence=result.confidence,
            momentum=result.momentum,
            africa_fit=result.africa_fit,
            risk=result.risk,
            radar_score=result.radar_score,
            outreach_score=result.outreach_score,
            outreach_qualified=result.outreach_gate_passed,
            state=result.state.value,
            # Workflow state is an analyst-owned field; scoring never resets it.
            workflow_state=previous_workflow,
            feature_vector={
                "confidence_breakdown": result.confidence_breakdown,
                "momentum_breakdown": result.momentum_breakdown,
                "risk_breakdown": result.risk_breakdown,
                "gate_failures": result.gate_failures,
                "risk_flags": risk_flags,
                "africa_label": africa_label,
                "verification": verification.get("liveness"),
            },
            rule_version=result.rule_version,
            calculated_at=result.calculated_at,
        )
        self.session.add(snapshot)
        await self.session.flush()

        # The candidate points at the newest snapshot; the history stays.
        candidate.current_score_id = snapshot.id
        await self.session.flush()

        if trigger_alerts and result.state == CandidateState.HOT and previous_state != "HOT":
            await self._dispatch_hot_alert(candidate, evidence_events, snapshot)
        return snapshot

    async def _active_signals(self, candidate_id: str) -> List[Signal]:
        stmt = select(Signal).where(Signal.candidate_id == candidate_id, Signal.active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _looks_token_only(candidate: ChainProduct) -> bool:
        """Token launches with no independent network are hard-blocked (spec 01)."""
        has_network_identity = any(
            (net.human_chain_id or net.caip2 or net.rpc_urls) for net in (candidate.networks or [])
        )
        if has_network_identity:
            return False
        labels = {str(p).lower() for p in (candidate.purpose_labels or [])}
        return "token" in labels or "token_only" in labels

    async def _dispatch_hot_alert(
        self,
        candidate: ChainProduct,
        evidence_events: Sequence[EvidenceEvent],
        snapshot: ScoreSnapshot,
    ) -> None:
        """Send a HOT alert unless an identical one is inside the dedup window."""
        dedup_key = stable_payload_hash(
            {
                "candidate": candidate.id,
                "state": snapshot.state,
                "stage": candidate.stage,
                "africa": candidate.assessment.intent_label if candidate.assessment else None,
                "evidence": len(evidence_events),
            }
        )
        window_start = utcnow() - timedelta(hours=settings.DEDUP_WINDOW_HOURS)
        stmt = select(AlertDispatch).where(
            AlertDispatch.dedup_key == dedup_key,
            AlertDispatch.dispatched_at >= window_start,
        )
        if (await self.session.execute(stmt)).scalars().first():
            logger.info("Suppressing duplicate HOT alert for %s inside dedup window", candidate.id)
            return

        card = EvidenceCardBuilder.build_card(candidate, list(evidence_events))
        delivered = False
        detail = None
        try:
            delivered = await webhook_dispatcher.dispatch_hot_alert(card)
        except Exception as exc:  # a failed webhook must not lose the candidate
            detail = str(exc)[:1000]
            logger.warning("HOT alert dispatch failed for %s: %s", candidate.id, exc)

        self.session.add(
            AlertDispatch(
                candidate_id=candidate.id,
                alert_type="HOT",
                state=snapshot.state,
                dedup_key=dedup_key,
                channel="webhook",
                delivered=bool(delivered),
                delivery_detail=detail,
                payload={"outreach_score": snapshot.outreach_score, "confidence": snapshot.confidence},
            )
        )

    # ------------------------------------------------------------------
    # Collector driver
    # ------------------------------------------------------------------
    async def run_collector_batch(
        self, collector: Collector, budget: Optional[RateBudget] = None
    ) -> int:
        """Run one collector fetch and process the batch.

        The cursor is advanced only after the evidence transaction commits, so a
        crash mid-batch replays from the last safe position instead of skipping
        events (spec 18).
        """
        budget = budget or RateBudget(remaining_requests=60)
        cursor_record = await self.repo.get_cursor(collector.source_id)
        cursor = Cursor(
            source_id=collector.source_id,
            etag=cursor_record.etag if cursor_record else None,
            last_modified=cursor_record.last_modified if cursor_record else None,
            cursor_token=cursor_record.cursor if cursor_record else None,
            last_seen_sha=cursor_record.safe_sha if cursor_record else None,
        )

        try:
            batch: FetchBatch = await collector.fetch(cursor, budget)
        except Exception as exc:
            await self.repo.save_cursor(
                source_id=collector.source_id,
                etag=cursor.etag,
                last_modified=cursor.last_modified,
                cursor=cursor.cursor_token,
                safe_sha=cursor.last_seen_sha,
                is_success=False,
            )
            logger.warning("Collector %s fetch failed: %s", collector.source_id, exc)
            raise

        processed = 0
        commit_every = max(1, settings.INGEST_COMMIT_EVERY)
        for raw_item in batch.items:
            await self.process_raw_item(collector, raw_item)
            processed += 1
            if processed % commit_every == 0:
                # Checkpoint mid-batch. A registry snapshot can carry thousands
                # of chains; holding one transaction across all of them keeps
                # row locks for minutes and makes any failure lose the whole
                # batch. Committing in chunks bounds both.
                await self.session.commit()

        next_cursor = collector.next_cursor(batch)
        await self.repo.save_cursor(
            source_id=collector.source_id,
            etag=next_cursor.etag,
            last_modified=next_cursor.last_modified,
            cursor=next_cursor.cursor_token,
            safe_sha=next_cursor.last_seen_sha,
            is_success=True,
        )
        return processed
