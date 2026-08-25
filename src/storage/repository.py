"""Repository providing transactional operations over evidence, candidates, and projections."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.types import (
    AfricaIntentLabel,
    CandidateState,
    Cursor,
    IncarnationStatus,
    LifecycleStage,
    NetworkEnvironment,
    RawItem,
    StackFamily,
    WorkflowState,
)
from src.storage.models import (
    AfricaAssessment,
    AuditLog,
    ChainProduct,
    Contact,
    EvidenceEvent,
    FundingRound,
    Network,
    NetworkIncarnation,
    ObservationLink,
    Opportunity,
    Organization,
    ScoreSnapshot,
    Signal,
    SourceCursor,
)
from src.storage.object_store import object_store
from src.config import settings
from src.util.redaction import redact_url
from src.util.timeutil import observed_bucket, utcnow


class Repository:
    """Encapsulates all database operations for the intelligence engine."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --------------------------------------------------------------------------
    # Evidence Ledger Operations
    # --------------------------------------------------------------------------

    async def append_evidence(self, raw: RawItem, raw_payload_path: Optional[str] = None) -> EvidenceEvent:
        """Append a raw evidence event, or return the existing row on replay.

        The idempotency key is ``source_id + external_id`` (spec 18). Content
        identity is a *separate* key that also carries the observation bucket,
        so re-seeing unchanged content in a later bucket records a genuine new
        observation instead of being silently swallowed - freshness and
        liveness both depend on that distinction.

        URLs are redacted before storage: an RPC endpoint may embed a provider
        API key, and evidence payloads must never carry credentials (spec 15).
        """
        bucket = observed_bucket(
            raw.observed_at, minutes=settings.VERIFY_EVIDENCE_BUCKET_MINUTES
        )

        # 1. Exact replay of the same source event.
        stmt = select(EvidenceEvent).where(
            EvidenceEvent.source_id == raw.source_id,
            EvidenceEvent.external_id == raw.external_id,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        # 2. Same bytes already recorded within this observation bucket.
        stmt = select(EvidenceEvent).where(
            EvidenceEvent.source_id == raw.source_id,
            EvidenceEvent.content_hash == raw.content_hash,
            EvidenceEvent.observed_bucket == bucket,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        provenance = raw.provenance or {}
        evidence = EvidenceEvent(
            source_id=raw.source_id,
            external_id=raw.external_id,
            url=redact_url(raw.url),
            source_family=raw.source_family,
            observed_at=raw.observed_at,
            published_at=raw.published_at,
            content_hash=raw.content_hash,
            observed_bucket=bucket,
            raw_payload_path=raw_payload_path,
            extracted_claims=provenance,
            reliability=provenance.get("reliability", 0.85),
            parser_version=provenance.get("parser_version", "1.0.0"),
        )
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    async def get_evidence(self, evidence_id: str) -> Optional[EvidenceEvent]:
        stmt = select(EvidenceEvent).where(EvidenceEvent.id == evidence_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_evidence_for_candidate(self, candidate_id: str) -> List[EvidenceEvent]:
        stmt = (
            select(EvidenceEvent)
            .join(ObservationLink, ObservationLink.evidence_id == EvidenceEvent.id)
            .where(ObservationLink.candidate_id == candidate_id)
            .order_by(desc(EvidenceEvent.observed_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def link_evidence_to_candidate(
        self, evidence_id: str, candidate_id: str, link_type: str = "primary_discovery"
    ) -> ObservationLink:
        stmt = select(ObservationLink).where(
            ObservationLink.evidence_id == evidence_id,
            ObservationLink.candidate_id == candidate_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        link = ObservationLink(
            evidence_id=evidence_id,
            candidate_id=candidate_id,
            link_type=link_type,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    # --------------------------------------------------------------------------
    # Cursor Operations
    # --------------------------------------------------------------------------

    async def get_cursor(self, source_id: str) -> Optional[SourceCursor]:
        stmt = select(SourceCursor).where(SourceCursor.source_id == source_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_cursor(
        self,
        source_id: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        cursor: Optional[str] = None,
        safe_sha: Optional[str] = None,
        is_success: bool = True,
    ) -> SourceCursor:
        sc = await self.get_cursor(source_id)
        now = datetime.now(timezone.utc)
        if not sc:
            sc = SourceCursor(
                source_id=source_id,
                etag=etag,
                last_modified=last_modified,
                cursor=cursor,
                safe_sha=safe_sha,
                last_success=now if is_success else None,
                consecutive_failures=0 if is_success else 1,
            )
            self.session.add(sc)
        else:
            if etag is not None:
                sc.etag = etag
            if last_modified is not None:
                sc.last_modified = last_modified
            if cursor is not None:
                sc.cursor = cursor
            if safe_sha is not None:
                sc.safe_sha = safe_sha
            if is_success:
                sc.last_success = now
                sc.consecutive_failures = 0
            else:
                sc.consecutive_failures += 1
            sc.updated_at = now
        await self.session.flush()
        return sc

    # --------------------------------------------------------------------------
    # Candidate & Entity Graph Operations
    # --------------------------------------------------------------------------

    async def get_candidate(self, candidate_id: str) -> Optional[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .options(
                selectinload(ChainProduct.organization),
                selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                selectinload(ChainProduct.assessment),
                selectinload(ChainProduct.score),
                selectinload(ChainProduct.signals),
                selectinload(ChainProduct.opportunities),
                selectinload(ChainProduct.contacts),
                selectinload(ChainProduct.funding_rounds),
                selectinload(ChainProduct.observation_links).selectinload(ObservationLink.evidence),
            )
            .where(ChainProduct.id == candidate_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_candidate_by_slug(self, slug: str) -> Optional[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .options(
                selectinload(ChainProduct.organization),
                selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                selectinload(ChainProduct.assessment),
                selectinload(ChainProduct.score),
                selectinload(ChainProduct.funding_rounds),
            )
            .where(ChainProduct.slug == slug)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_candidate_by_caip2_or_chain_id(self, caip2: Optional[str], chain_id: Optional[str]) -> Optional[ChainProduct]:
        if not caip2 and not chain_id:
            return None
        stmt = (
            select(ChainProduct)
            .join(Network, Network.chain_product_id == ChainProduct.id)
            .options(
                selectinload(ChainProduct.organization),
                selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                selectinload(ChainProduct.assessment),
                selectinload(ChainProduct.score),
                selectinload(ChainProduct.funding_rounds),
            )
        )
        if caip2:
            stmt = stmt.where(Network.caip2 == caip2)
        elif chain_id:
            stmt = stmt.where(Network.human_chain_id == str(chain_id))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def find_organization_by_domain_or_name(self, domain: Optional[str], name: Optional[str]) -> Optional[Organization]:
        if domain:
            # Check domains array
            stmt = select(Organization)
            result = await self.session.execute(stmt)
            orgs = result.scalars().all()
            for org in orgs:
                if domain in org.official_domains:
                    return org
        if name:
            name_lower = name.lower().strip()
            stmt = select(Organization).where(
                or_(
                    func.lower(Organization.display_name) == name_lower,
                    func.lower(Organization.legal_name) == name_lower,
                )
            )
            result = await self.session.execute(stmt)
            return result.scalars().first()
        return None

    async def list_candidates(
        self,
        state: Optional[str] = None,
        workflow_state: Optional[str] = None,
        africa_intent: Optional[str] = None,
        stack_family: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        verified_only: bool = False,
    ) -> List[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .options(
                selectinload(ChainProduct.organization),
                selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                selectinload(ChainProduct.assessment),
                selectinload(ChainProduct.score),
                selectinload(ChainProduct.signals),
                selectinload(ChainProduct.opportunities),
                selectinload(ChainProduct.contacts),
                selectinload(ChainProduct.funding_rounds),
            )
            # Join the CURRENT snapshot, not the history. Score snapshots are
            # append-only, so joining on candidate_id multiplies each candidate
            # by its number of rescores and sorts on an arbitrary old score.
            .outerjoin(ScoreSnapshot, ScoreSnapshot.id == ChainProduct.current_score_id)
            .outerjoin(AfricaAssessment, AfricaAssessment.candidate_id == ChainProduct.id)
        )
        if state:
            stmt = stmt.where(ScoreSnapshot.state == state)
        if workflow_state:
            stmt = stmt.where(ScoreSnapshot.workflow_state == workflow_state)
        if africa_intent:
            stmt = stmt.where(AfricaAssessment.intent_label == africa_intent)
        if stack_family:
            stmt = stmt.where(ChainProduct.stack_family == stack_family)
        if search_query:
            sq = f"%{search_query.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(ChainProduct.canonical_name).like(sq),
                    func.lower(ChainProduct.slug).like(sq),
                )
            )
        if verified_only:
            stmt = stmt.where(ChainProduct.last_verified_at.isnot(None))

        # NULLS LAST so unscored candidates never outrank scored ones.
        stmt = stmt.order_by(
            desc(ScoreSnapshot.outreach_score).nullslast(),
            desc(ScoreSnapshot.radar_score).nullslast(),
            desc(ChainProduct.first_seen_at),
        )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_candidates(
        self,
        state: Optional[str] = None,
        workflow_state: Optional[str] = None,
        africa_intent: Optional[str] = None,
        stack_family: Optional[str] = None,
        search_query: Optional[str] = None,
        verified_only: bool = False,
    ) -> int:
        """Total matching candidates, for pagination."""
        stmt = (
            select(func.count(func.distinct(ChainProduct.id)))
            .select_from(ChainProduct)
            .outerjoin(ScoreSnapshot, ScoreSnapshot.id == ChainProduct.current_score_id)
            .outerjoin(AfricaAssessment, AfricaAssessment.candidate_id == ChainProduct.id)
        )
        if state:
            stmt = stmt.where(ScoreSnapshot.state == state)
        if workflow_state:
            stmt = stmt.where(ScoreSnapshot.workflow_state == workflow_state)
        if africa_intent:
            stmt = stmt.where(AfricaAssessment.intent_label == africa_intent)
        if stack_family:
            stmt = stmt.where(ChainProduct.stack_family == stack_family)
        if search_query:
            sq = f"%{search_query.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(ChainProduct.canonical_name).like(sq),
                    func.lower(ChainProduct.slug).like(sq),
                )
            )
        if verified_only:
            stmt = stmt.where(ChainProduct.last_verified_at.isnot(None))
        return int(await self.session.scalar(stmt) or 0)

    # --------------------------------------------------------------------------
    # Contacts & Privacy Suppression Operations
    # --------------------------------------------------------------------------

    async def is_suppressed(self, channel_value: str) -> bool:
        """Checks if a normalized contact channel (email/form/url) is suppressed."""
        norm_val = channel_value.lower().strip()
        ch_hash = hashlib.sha256(norm_val.encode("utf-8")).hexdigest()
        stmt = select(Contact).where(
            Contact.channel_hash == ch_hash,
            Contact.suppressed == True,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def add_suppression(self, channel_value: str, reason: str = "Opt-out / Privacy request", actor: str = "analyst") -> None:
        norm_val = channel_value.lower().strip()
        ch_hash = hashlib.sha256(norm_val.encode("utf-8")).hexdigest()
        stmt = select(Contact).where(Contact.channel_hash == ch_hash)
        result = await self.session.execute(stmt)
        contacts = list(result.scalars().all())
        now = datetime.now(timezone.utc)
        if contacts:
            for c in contacts:
                c.suppressed = True
                c.suppression_reason = reason
        else:
            # Create a placeholder suppressed record
            sc = Contact(
                role_type="suppressed",
                channel_type="suppressed",
                channel_value="[REDACTED-HASH-ONLY]",
                channel_hash=ch_hash,
                permitted_purpose="none",
                source_url="internal_suppression_list",
                suppressed=True,
                suppression_reason=reason,
                last_verified_at=now,
            )
            self.session.add(sc)
        
        # Log in audit
        await self.append_audit_log(
            actor=actor,
            action="contact_suppression",
            target_type="contact",
            target_id=ch_hash,
            after_state={"suppressed": True, "reason": reason},
            reason=reason,
        )
        await self.session.flush()

    # --------------------------------------------------------------------------
    # Audit Log Operations
    # --------------------------------------------------------------------------

    async def append_audit_log(
        self,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> AuditLog:
        log = AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    # --------------------------------------------------------------------------
    # Funding Operations (Spec 13: Capital)
    # --------------------------------------------------------------------------

    async def record_funding_round(
        self,
        candidate_id: str,
        round_type: str,
        amount_usd: Optional[float],
        amount_as_published: Optional[str],
        currency: str,
        investors: List[str],
        lead_investor: Optional[str],
        source_url: str,
        quote: Optional[str] = None,
        confidence: float = 0.8,
        announced_at: Optional[datetime] = None,
        org_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> FundingRound:
        """Records an announced funding event idempotently."""
        # Deduplication check
        stmt = select(FundingRound).where(
            FundingRound.candidate_id == candidate_id,
            FundingRound.round_type == round_type,
            FundingRound.amount_as_published == amount_as_published,
        )
        if announced_at:
            stmt = stmt.where(FundingRound.announced_at == announced_at)
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            # Update fields if new data has higher confidence
            if confidence > existing.confidence:
                existing.confidence = confidence
                existing.investors = list(dict.fromkeys((existing.investors or []) + investors))
                if lead_investor and not existing.lead_investor:
                    existing.lead_investor = lead_investor
                if quote and not existing.quote:
                    existing.quote = quote
                await self.session.flush()
            return existing

        round_obj = FundingRound(
            candidate_id=candidate_id,
            org_id=org_id,
            round_type=round_type,
            amount_usd=amount_usd,
            amount_as_published=amount_as_published,
            currency=currency,
            investors=investors,
            lead_investor=lead_investor,
            source_url=source_url,
            evidence_id=evidence_id,
            quote=quote,
            confidence=confidence,
            announced_at=announced_at,
        )
        self.session.add(round_obj)
        await self.session.flush()
        return round_obj

    async def get_funding_rounds_for_candidate(self, candidate_id: str) -> List[FundingRound]:
        stmt = (
            select(FundingRound)
            .where(FundingRound.candidate_id == candidate_id)
            .order_by(desc(FundingRound.announced_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
