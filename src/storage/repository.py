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


class Repository:
    """Encapsulates all database operations for the intelligence engine."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --------------------------------------------------------------------------
    # Evidence Ledger Operations
    # --------------------------------------------------------------------------

    async def append_evidence(self, raw: RawItem, raw_payload_path: Optional[str] = None) -> EvidenceEvent:
        """Appends a new raw evidence event to the append-only ledger or returns existing if duplicate."""
        stmt = select(EvidenceEvent).where(
            EvidenceEvent.source_id == raw.source_id,
            or_(
                EvidenceEvent.external_id == raw.external_id,
                EvidenceEvent.content_hash == raw.content_hash,
            ),
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        evidence = EvidenceEvent(
            source_id=raw.source_id,
            external_id=raw.external_id,
            url=raw.url,
            source_family=raw.source_family,
            observed_at=raw.observed_at,
            published_at=raw.published_at,
            content_hash=raw.content_hash,
            raw_payload_path=raw_payload_path,
            extracted_claims=raw.provenance or {},
            reliability=raw.provenance.get("reliability", 0.85),
            parser_version=raw.provenance.get("parser_version", "1.0.0"),
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
            )
            .outerjoin(ScoreSnapshot, ScoreSnapshot.candidate_id == ChainProduct.id)
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

        stmt = stmt.order_by(desc(ScoreSnapshot.outreach_score), desc(ChainProduct.first_seen_at))
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
