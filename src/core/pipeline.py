"""Central Intelligence Pipeline orchestrating collection, normalization, verification, scoring, and alerting."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.alerting.evidence_card import EvidenceCardBuilder
from src.alerting.webhooks import webhook_dispatcher
from src.classifiers.africa import africa_classifier
from src.classifiers.opportunity import opportunity_classifier
from src.classifiers.risk import risk_evaluator
from src.collectors.base import Collector
from src.core.lifecycle import LifecycleManager
from src.core.normalizer import extract_effective_domain
from src.core.resolver import EntityResolver
from src.core.types import (
    CandidateState,
    Cursor,
    FetchBatch,
    LifecycleStage,
    RateBudget,
    RawItem,
    RawObservation,
    WorkflowState,
)
from src.scoring.engine import scoring_engine
from src.storage.database import db_manager
from src.storage.models import Contact, Opportunity, ScoreSnapshot
from src.storage.object_store import object_store
from src.storage.repository import Repository
from src.verifier.engine import verifier_engine

logger = logging.getLogger(__name__)


class IntelligencePipeline:
    """End-to-end execution pipeline for early chain discovery."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = Repository(session)
        self.resolver = EntityResolver(session)

    async def process_raw_item(self, collector: Collector, raw: RawItem) -> List[str]:
        """Processes a single raw item through the append-only ledger, normalizer, resolver, verifier, and scorer.
        
        Returns:
            List[candidate_ids]
        """
        # 1. Store compressed payload
        content_hash, payload_path = object_store.store_payload(collector.source_id, raw.raw_payload)
        raw.content_hash = content_hash
        
        # 2. Append to immutable Evidence Event Ledger
        evidence = await self.repo.append_evidence(raw, raw_payload_path=payload_path)

        # 3. Normalize to standardized observations
        observations = collector.normalize(raw)
        affected_candidate_ids: List[str] = []

        for obs in observations:
            # 4. Entity graph resolution & candidate upsert
            candidate, is_new = await self.resolver.upsert_candidate(obs, evidence.id)
            affected_candidate_ids.append(candidate.id)

            # 5. Update timestamps & compute current stage
            LifecycleManager.update_timestamps_from_claims(candidate, obs.claims)
            candidate.stage = LifecycleManager.compute_current_stage(candidate, networks=candidate.networks).value

            # 6. Opportunities extraction
            raw_text = obs.raw_text or ""
            opps = opportunity_classifier.classify(raw_text)
            for opp_type, response_suggestion, snippet in opps:
                opp_record = Opportunity(
                    candidate_id=candidate.id,
                    opportunity_type=opp_type.value,
                    geography=", ".join(obs.claimed_locations) if obs.claimed_locations else "Global",
                    summary=f"{response_suggestion} (Matched: {snippet})",
                    evidence_refs=[evidence.id],
                )
                self.session.add(opp_record)

            # 7. Contacts extraction & suppression verification
            for ct in obs.contacts:
                val = ct.get("channel_value", "")
                if val and not await self.repo.is_suppressed(val):
                    import hashlib
                    ch_hash = hashlib.sha256(val.lower().strip().encode("utf-8")).hexdigest()
                    contact_record = Contact(
                        org_id=candidate.organization_id,
                        candidate_id=candidate.id,
                        role_type=ct.get("role_type", "business_contact"),
                        name=ct.get("name"),
                        channel_type=ct.get("channel_type", "form"),
                        channel_value=val,
                        channel_hash=ch_hash,
                        permitted_purpose=ct.get("permitted_purpose", "partnership_inquiry"),
                        source_url=ct.get("source_url", raw.url),
                        suppressed=False,
                    )
                    self.session.add(contact_record)

            # 8. Africa Classification
            is_official = getattr(collector, "tier", "A") == "A" or obs.reliability >= 0.85
            has_domain = bool(candidate.organization and candidate.organization.official_domains) if candidate.organization else False
            vec, label = africa_classifier.evaluate_feature_vector(
                raw_text,
                is_official_source=is_official,
                has_public_contact=bool(obs.contacts or has_domain),
            )

            # Update Africa Assessment
            if candidate.assessment:
                # Retain analyst override if exists
                if not candidate.assessment.analyst_override:
                    candidate.assessment.intent_label = label.value
                    candidate.assessment.confidence = vec.confidence
                    candidate.assessment.countries = vec.matched_countries
                    candidate.assessment.regions = vec.matched_regions
                    candidate.assessment.languages = vec.matched_languages
                    candidate.assessment.rails_use_cases = vec.matched_rails
                    candidate.assessment.explicit_geo_score = vec.explicit_geo
                    candidate.assessment.regional_action_score = vec.regional_action
                    candidate.assessment.use_case_fit_score = vec.use_case_fit
                    candidate.assessment.whitespace_score = vec.whitespace
                    candidate.assessment.contactability_score = vec.contactability
                    candidate.assessment.operating_capacity_score = vec.operating_capacity
                    candidate.assessment.total_score = vec.total_score
                    if evidence.id not in candidate.assessment.evidence_ids:
                        candidate.assessment.evidence_ids = list(set(candidate.assessment.evidence_ids + [evidence.id]))

            # 9. Verifier probe (if RPC URL available and not verified yet)
            has_tech_verification = False
            for net in candidate.networks:
                if net.rpc_urls and not candidate.last_verified_at:
                    for rpc in net.rpc_urls[:2]:
                        probe_res = await verifier_engine.probe_endpoint(rpc, family=candidate.stack_family)
                        if probe_res.success and probe_res.head:
                            has_tech_verification = True
                            candidate.last_verified_at = probe_res.checked_at
                            if probe_res.identity and probe_res.identity.genesis_hash:
                                for inc in net.incarnations:
                                    inc.genesis_fingerprint = probe_res.identity.genesis_hash
                                    inc.last_verified_at = probe_res.checked_at
                                    inc.last_observed_height = probe_res.head.block_height
                            break

            # 10. Rescore Candidate & Update ScoreSnapshot
            evidence_events = await self.repo.list_evidence_for_candidate(candidate.id)
            if evidence not in evidence_events:
                evidence_events.append(evidence)

            # Evaluate Risk Penalties
            risk_score, risk_bd, risk_flags = risk_evaluator.evaluate_risk(
                has_identity_mismatch=False,
                is_impersonation_or_unattributed=not (candidate.organization_id or candidate.repo_created_at),
                is_token_only_or_content_farm="token" in candidate.canonical_name.lower() and not candidate.networks,
            )

            score_res = scoring_engine.evaluate(
                chain=candidate,
                evidence_events=evidence_events,
                africa_fit=candidate.assessment.total_score if candidate.assessment else 0.0,
                risk=risk_score,
                risk_breakdown=risk_bd,
                has_technical_fingerprint=bool(candidate.last_verified_at or has_tech_verification),
            )

            old_state = candidate.score.state if candidate.score else "RADAR"
            
            if candidate.score:
                candidate.score.confidence = score_res.confidence
                candidate.score.momentum = score_res.momentum
                candidate.score.africa_fit = score_res.africa_fit
                candidate.score.risk = score_res.risk
                candidate.score.radar_score = score_res.radar_score
                candidate.score.outreach_score = score_res.outreach_score
                candidate.score.outreach_qualified = score_res.outreach_gate_passed
                candidate.score.state = score_res.state.value
                candidate.score.feature_vector = {
                    "confidence_breakdown": score_res.confidence_breakdown,
                    "momentum_breakdown": score_res.momentum_breakdown,
                    "risk_breakdown": score_res.risk_breakdown,
                    "gate_failures": score_res.gate_failures,
                    "risk_flags": risk_flags,
                }
                candidate.score.calculated_at = score_res.calculated_at

            await self.session.flush()

            # 11. Trigger HOT alert if newly entered HOT state
            if score_res.state == CandidateState.HOT and old_state != "HOT":
                card = EvidenceCardBuilder.build_card(candidate, evidence_events)
                await webhook_dispatcher.dispatch_hot_alert(card)

        return affected_candidate_ids

    async def run_collector_batch(self, collector: Collector, budget: Optional[RateBudget] = None) -> int:
        """Executes a single collector fetch batch and processes items in an atomic transaction."""
        budget = budget or RateBudget(remaining_requests=60)
        
        # Load Cursor
        cursor_record = await self.repo.get_cursor(collector.source_id)
        cur = Cursor(
            source_id=collector.source_id,
            etag=cursor_record.etag if cursor_record else None,
            last_modified=cursor_record.last_modified if cursor_record else None,
            cursor_token=cursor_record.cursor if cursor_record else None,
            last_seen_sha=cursor_record.safe_sha if cursor_record else None,
        )

        batch: FetchBatch = await collector.fetch(cur, budget)
        processed_count = 0

        for raw_item in batch.items:
            await self.process_raw_item(collector, raw_item)
            processed_count += 1

        # Commit new cursor after successful evidence transaction
        next_c = collector.next_cursor(batch)
        await self.repo.save_cursor(
            source_id=collector.source_id,
            etag=next_c.etag,
            last_modified=next_c.last_modified,
            cursor=next_c.cursor_token,
            safe_sha=next_c.last_seen_sha,
            is_success=True,
        )

        return processed_count
