"""Entity resolution, deduplication, and collision/reset handling."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.normalizer import (
    extract_effective_domain,
    format_caip2,
    normalize_chain_id,
    normalize_name,
    slugify,
    strip_legal_suffixes,
)
from src.core.types import (
    CandidateState,
    IncarnationStatus,
    LifecycleStage,
    NetworkEnvironment,
    RawObservation,
    StackFamily,
    WorkflowState,
)
from src.storage.models import (
    AfricaAssessment,
    ChainProduct,
    Contact,
    Network,
    NetworkIncarnation,
    ObservationLink,
    Opportunity,
    Organization,
    ScoreSnapshot,
    Signal,
)


def stable_uuid(*args: Any) -> str:
    """Generates deterministic UUIDv5 from concatenated string keys."""
    raw_key = ":".join(str(a or "").strip().lower() for a in args)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_key))


class EntityResolver:
    """Resolves incoming observations to canonical Organization, ChainProduct, Network, and Incarnations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve_organization(self, obs: RawObservation) -> Organization:
        """Resolves or creates an Organization based on domain, GitHub org, or name."""
        display_name = obs.organization_name or obs.candidate_name
        norm_name = strip_legal_suffixes(display_name)
        
        # 1. Match by official domain (Weight 0.95)
        for dom in obs.organization_domains:
            if not dom:
                continue
            eff_dom = extract_effective_domain(dom)
            if eff_dom:
                stmt = select(Organization)
                res = await self.session.execute(stmt)
                for org in res.scalars().all():
                    if eff_dom in org.official_domains:
                        if obs.github_orgs:
                            for gh in obs.github_orgs:
                                if gh not in org.github_orgs:
                                    org.github_orgs = list(set(org.github_orgs + [gh]))
                        return org

        # 2. Match by GitHub Org (Weight 0.85)
        for gh in obs.github_orgs:
            if not gh:
                continue
            stmt = select(Organization)
            res = await self.session.execute(stmt)
            for org in res.scalars().all():
                if gh in org.github_orgs:
                    return org

        # 3. Create new organization with deterministic stable UUID
        org_slug = slugify(norm_name)
        org_id = stable_uuid("org", org_slug)
        
        stmt = select(Organization).where(Organization.org_id == org_id)
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        domains = [extract_effective_domain(d) for d in obs.organization_domains if extract_effective_domain(d)]
        org = Organization(
            org_id=org_id,
            display_name=display_name,
            legal_name=obs.organization_name,
            official_domains=list(set(domains)),
            github_orgs=obs.github_orgs,
            social_handles=obs.social_handles,
            claimed_locations=obs.claimed_locations,
            aliases=[norm_name],
        )
        self.session.add(org)
        await self.session.flush()
        return org

    async def upsert_candidate(
        self, obs: RawObservation, evidence_id: str
    ) -> Tuple[ChainProduct, bool]:
        """Resolves or creates a ChainProduct and links evidence.
        
        Returns:
            Tuple[ChainProduct, is_new_candidate]
        """
        org = await self.resolve_organization(obs)
        canonical_slug = obs.candidate_slug or slugify(strip_legal_suffixes(obs.candidate_name))
        
        # Check CAIP-2 or chain ID match first
        norm_chain_id = normalize_chain_id(obs.human_chain_id)
        caip2 = obs.caip2
        if not caip2 and norm_chain_id:
            ns = obs.protocol_namespace or ("eip155" if obs.stack_family == StackFamily.EVM else str(obs.stack_family.value))
            caip2 = format_caip2(ns, norm_chain_id)

        chain_product = None
        is_new = False

        # Attempt to find by CAIP-2
        if caip2:
            stmt = (
                select(ChainProduct)
                .join(Network, Network.chain_product_id == ChainProduct.id)
                .options(
                    selectinload(ChainProduct.organization),
                    selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                    selectinload(ChainProduct.assessment),
                    selectinload(ChainProduct.score),
                )
                .where(Network.caip2 == caip2)
            )
            res = await self.session.execute(stmt)
            chain_product = res.scalars().first()

        # If not found by CAIP-2, match by slug + org
        if not chain_product:
            candidate_id = stable_uuid(org.org_id, canonical_slug)
            stmt = (
                select(ChainProduct)
                .options(
                    selectinload(ChainProduct.organization),
                    selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                    selectinload(ChainProduct.assessment),
                    selectinload(ChainProduct.score),
                )
                .where(ChainProduct.id == candidate_id)
            )
            res = await self.session.execute(stmt)
            chain_product = res.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        
        if not chain_product:
            is_new = True
            candidate_id = stable_uuid(org.org_id, canonical_slug)
            chain_product = ChainProduct(
                id=candidate_id,
                organization_id=org.org_id,
                canonical_name=obs.candidate_name,
                slug=canonical_slug,
                aliases=[obs.candidate_name, strip_legal_suffixes(obs.candidate_name)],
                purpose_labels=obs.purpose_labels,
                stack_family=obs.stack_family.value if isinstance(obs.stack_family, StackFamily) else str(obs.stack_family),
                stack_details=obs.stack_details,
                layer=obs.layer or "L2",
                stage=obs.stage.value if isinstance(obs.stage, LifecycleStage) else str(obs.stage),
                first_seen_at=now,
            )
            self.session.add(chain_product)
            await self.session.flush()

            # Initialize Default Assessment & Score Snapshot
            assessment = AfricaAssessment(
                candidate_id=chain_product.id,
                intent_label="A4_no_evidence",
                readiness=0.0,
                whitespace=10.0,
                countries=[],
                regions=[],
                languages=[],
                rails_use_cases=[],
                evidence_ids=[evidence_id],
                confidence=0.0,
            )
            self.session.add(assessment)

            score_snap = ScoreSnapshot(
                candidate_id=chain_product.id,
                confidence=20.0 if obs.reliability > 0.8 else 10.0,
                momentum=30.0,
                africa_fit=0.0,
                risk=0.0,
                radar_score=20.0,
                outreach_score=10.0,
                outreach_qualified=False,
                state="RADAR",
                workflow_state="NEW",
                feature_vector={},
            )
            self.session.add(score_snap)
            await self.session.flush()

        # Link Network Environment & Incarnations
        await self._resolve_network_and_incarnation(chain_product, obs)

        # Link Observation Evidence Link
        stmt = select(ObservationLink).where(
            ObservationLink.evidence_id == evidence_id,
            ObservationLink.candidate_id == chain_product.id,
        )
        res = await self.session.execute(stmt)
        if not res.scalar_one_or_none():
            link = ObservationLink(
                evidence_id=evidence_id,
                candidate_id=chain_product.id,
                link_type="primary_discovery" if is_new else "corroboration",
            )
            self.session.add(link)

        await self.session.flush()
        
        # Eagerly load all relationships for downstream pipeline operations
        stmt_full = (
            select(ChainProduct)
            .options(
                selectinload(ChainProduct.organization),
                selectinload(ChainProduct.networks).selectinload(Network.incarnations),
                selectinload(ChainProduct.assessment),
                selectinload(ChainProduct.score),
                selectinload(ChainProduct.signals),
                selectinload(ChainProduct.opportunities),
                selectinload(ChainProduct.contacts),
                selectinload(ChainProduct.observation_links),
            )
            .where(ChainProduct.id == chain_product.id)
        )
        res_full = await self.session.execute(stmt_full)
        full_cand = res_full.scalar_one()

        return full_cand, is_new

    async def _resolve_network_and_incarnation(
        self, chain_product: ChainProduct, obs: RawObservation
    ) -> None:
        """Resolves Network environment and manages genesis incarnations and testnet resets."""
        env = obs.environment.value if isinstance(obs.environment, NetworkEnvironment) else str(obs.environment)
        proto_ns = obs.protocol_namespace or ("eip155" if chain_product.stack_family == "evm" else chain_product.stack_family)
        norm_chain_id = normalize_chain_id(obs.human_chain_id)
        caip2 = obs.caip2 or (format_caip2(proto_ns, norm_chain_id) if norm_chain_id else None)
        
        network_id = stable_uuid(chain_product.id, env, proto_ns)
        stmt = select(Network).options(selectinload(Network.incarnations)).where(Network.id == network_id)
        res = await self.session.execute(stmt)
        net = res.scalar_one_or_none()

        if not net:
            net = Network(
                id=network_id,
                chain_product_id=chain_product.id,
                environment=env,
                is_public=obs.is_public,
                caip2=caip2,
                protocol_namespace=proto_ns,
                human_chain_id=norm_chain_id,
                rpc_urls=obs.rpc_urls,
                explorer_urls=obs.explorer_urls,
                faucet_urls=obs.faucet_urls,
                launch_claims=obs.claims,
            )
            self.session.add(net)
            await self.session.flush()
        else:
            # Merge endpoints
            net.rpc_urls = list(set(net.rpc_urls + obs.rpc_urls))
            net.explorer_urls = list(set(net.explorer_urls + obs.explorer_urls))
            net.faucet_urls = list(set(net.faucet_urls + obs.faucet_urls))
            if caip2 and not net.caip2:
                net.caip2 = caip2
            if norm_chain_id and not net.human_chain_id:
                net.human_chain_id = norm_chain_id

        # Incarnation Handling (Genesis & Resets)
        genesis_fp = obs.genesis_fingerprint or "unknown_genesis_pending_probe"
        inc_id = stable_uuid(net.id, genesis_fp)

        stmt = select(NetworkIncarnation).where(NetworkIncarnation.id == inc_id)
        res = await self.session.execute(stmt)
        inc = res.scalar_one_or_none()

        if not inc:
            # Check if there was an active previous incarnation (Testnet Reset!)
            if genesis_fp != "unknown_genesis_pending_probe":
                stmt_prev = select(NetworkIncarnation).where(
                    NetworkIncarnation.network_id == net.id,
                    NetworkIncarnation.status == IncarnationStatus.ACTIVE.value,
                )
                res_prev = await self.session.execute(stmt_prev)
                prev_incs = res_prev.scalars().all()
                for prev in prev_incs:
                    if prev.genesis_fingerprint != genesis_fp:
                        # Supersede old incarnation
                        prev.status = IncarnationStatus.SUPERSEDED.value
                        prev.superseded_by_id = inc_id

            inc = NetworkIncarnation(
                id=inc_id,
                network_id=net.id,
                genesis_fingerprint=genesis_fp,
                genesis_time=obs.genesis_time,
                status=IncarnationStatus.ACTIVE.value,
            )
            self.session.add(inc)
            await self.session.flush()
