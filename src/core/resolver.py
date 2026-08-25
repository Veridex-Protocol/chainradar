"""Entity resolution, deduplication, and collision/reset handling (spec 16).

The governing rule is that strong *technical* and *official* relationships may
merge records automatically, while names and symbols may not. Concretely:

* A verified genesis fingerprint under the same protocol identity is proof of
  the same network incarnation (weight 1.00) and auto-links.
* A shared official domain or GitHub organization auto-links organizations.
* A CAIP-2 match alone does **not** merge across organizations. EVM chain-ID
  collisions between unrelated projects are expected, so a collision produces
  two candidates, a risk flag and an analyst review task.
* A normalized-name match alone never merges anything; it opens a review task.

Incarnations are only ever created from a *verified* genesis fingerprint. The
incarnation table is the technical identity of record, so a placeholder written
before verification would corrupt exactly the thing it exists to prove.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.core.normalizer import (
    extract_effective_domain,
    format_caip2,
    normalize_chain_id,
    normalize_name,
    slugify,
    strip_legal_suffixes,
)
from src.core.types import (
    IncarnationStatus,
    LifecycleStage,
    NetworkEnvironment,
    RawObservation,
    StackFamily,
)
from src.storage.models import (
    AfricaAssessment,
    ChainProduct,
    Network,
    NetworkIncarnation,
    ObservationLink,
    Organization,
    ReviewTask,
    Signal,
)

# Resolution weights (spec 16). Anything at or above AUTO_LINK may merge; the
# band between REVIEW and AUTO_LINK opens an analyst task; below REVIEW is
# ignored for identity purposes.
WEIGHT_EXACT_PROTOCOL_AND_GENESIS = 1.00
WEIGHT_SAME_OFFICIAL_DOMAIN = 0.95
WEIGHT_OFFICIAL_REPO_DOCS_LINK = 0.90
WEIGHT_SAME_EXPLORER_RPC_HOST_AND_CHAIN_ID = 0.85
WEIGHT_SAME_GITHUB_ORG_AND_WEBSITE = 0.85
WEIGHT_NAME_PLUS_HANDLE = 0.65
WEIGHT_NAME_ONLY = 0.40
WEIGHT_TICKER_ONLY = 0.10

AUTO_LINK_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.60

# Sentinel used where a foreign candidate is not applicable. An empty string
# rather than NULL, because NULLs do not collide in a unique constraint and the
# open-task uniqueness guard would stop working.
NO_RELATED = ""


def stable_uuid(*args: Any) -> str:
    """Deterministic UUIDv5 over the given key parts (spec 04)."""
    raw_key = ":".join(str(a or "").strip().lower() for a in args)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_key))


def _json_contains(column, value: str):
    """Dialect-aware containment test against a JSON array column.

    On PostgreSQL this compiles to the ``@>`` operator and is served by the GIN
    indexes created in migration 0002. That matters: the previous
    implementation loaded every organization row and filtered in Python, an
    O(rows) scan per observation.
    """
    return cast(column, JSONB).contains(cast([value], JSONB))


class EntityResolver:
    """Resolves observations onto organizations, chains, networks and incarnations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # -- review tasks ------------------------------------------------------
    async def open_review_task(
        self,
        task_type: str,
        reason: str,
        *,
        candidate_id: Optional[str] = None,
        related_candidate_id: str = NO_RELATED,
        match_weight: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
        evidence_refs: Optional[Sequence[str]] = None,
    ) -> Optional[ReviewTask]:
        """Record an analyst decision the engine refuses to make on its own.

        Idempotent: re-observing the same collision on every poll must not
        create a new task each time.
        """
        stmt = select(ReviewTask).where(
            ReviewTask.task_type == task_type,
            ReviewTask.candidate_id == candidate_id,
            ReviewTask.related_candidate_id == related_candidate_id,
            ReviewTask.status == "open",
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            merged_refs = list(dict.fromkeys(list(existing.evidence_refs) + list(evidence_refs or [])))
            existing.evidence_refs = merged_refs
            return existing

        task = ReviewTask(
            task_type=task_type,
            candidate_id=candidate_id,
            related_candidate_id=related_candidate_id,
            match_weight=match_weight,
            reason=reason,
            details=details or {},
            evidence_refs=list(evidence_refs or []),
            status="open",
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def _raise_risk_signal(
        self, candidate_id: str, signal_type: str, evidence_id: Optional[str], detail: str
    ) -> None:
        """Attach a negative signal so the risk scorer can see it."""
        stmt = select(Signal).where(
            Signal.candidate_id == candidate_id,
            Signal.signal_type == signal_type,
            Signal.active.is_(True),
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            if evidence_id and evidence_id not in existing.evidence_refs:
                existing.evidence_refs = list(existing.evidence_refs) + [evidence_id]
            return
        self.session.add(
            Signal(
                candidate_id=candidate_id,
                signal_type=signal_type,
                polarity="negative",
                strength=1.0,
                lifecycle_implication=detail,
                evidence_refs=[evidence_id] if evidence_id else [],
                active=True,
            )
        )

    # -- organizations -----------------------------------------------------
    async def resolve_organization(self, obs: RawObservation) -> Organization:
        """Resolve or create an organization using indexed, evidence-backed keys."""
        display_name = obs.organization_name or obs.candidate_name
        norm_name = normalize_name(display_name)
        domains = [d for d in (extract_effective_domain(x) for x in obs.organization_domains) if d]
        github_orgs = [g.strip() for g in obs.github_orgs if g and g.strip()]

        # 1. Shared official domain (0.95) - indexed containment lookup.
        for domain in domains:
            stmt = select(Organization).where(_json_contains(Organization.official_domains, domain))
            org = (await self.session.execute(stmt)).scalars().first()
            if org:
                self._merge_org_identifiers(org, domains, github_orgs, obs)
                return org

        # 2. Shared GitHub organization (0.85) - indexed containment lookup.
        for gh in github_orgs:
            stmt = select(Organization).where(_json_contains(Organization.github_orgs, gh))
            org = (await self.session.execute(stmt)).scalars().first()
            if org:
                self._merge_org_identifiers(org, domains, github_orgs, obs)
                return org

        # 3. No strong identifier: create a distinct organization. The key uses
        #    the *full* normalized name, not the suffix-stripped form, so that
        #    "Kora Network" and "Kora Labs" do not silently become one entity
        #    on a 0.40-weight name match.
        org_id = stable_uuid("org", slugify(norm_name) or slugify(display_name))
        stmt = select(Organization).where(Organization.org_id == org_id)
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            self._merge_org_identifiers(existing, domains, github_orgs, obs)
            return existing

        org = Organization(
            org_id=org_id,
            display_name=display_name,
            legal_name=obs.organization_name,
            official_domains=sorted(set(domains)),
            github_orgs=sorted(set(github_orgs)),
            social_handles=obs.social_handles,
            claimed_locations=obs.claimed_locations,
            # The suffix-stripped form is retained as an alias for matching,
            # never as identity (spec 16 normalization note).
            aliases=sorted({norm_name, strip_legal_suffixes(display_name)} - {""}),
        )
        self.session.add(org)
        await self.session.flush()
        return org

    @staticmethod
    def _merge_org_identifiers(
        org: Organization,
        domains: Sequence[str],
        github_orgs: Sequence[str],
        obs: RawObservation,
    ) -> None:
        """Accumulate newly observed identifiers onto a matched organization."""
        if domains:
            org.official_domains = sorted(set(list(org.official_domains) + list(domains)))
        if github_orgs:
            org.github_orgs = sorted(set(list(org.github_orgs) + list(github_orgs)))
        if obs.social_handles:
            merged = dict(org.social_handles)
            merged.update(obs.social_handles)
            org.social_handles = merged
        if obs.claimed_locations:
            org.claimed_locations = sorted(set(list(org.claimed_locations) + list(obs.claimed_locations)))

    # -- candidates --------------------------------------------------------
    async def upsert_candidate(
        self, obs: RawObservation, evidence_id: str
    ) -> Tuple[ChainProduct, bool]:
        """Resolve or create a chain product and attach the evidence edge."""
        org = await self.resolve_organization(obs)
        canonical_slug = obs.candidate_slug or slugify(normalize_name(obs.candidate_name))

        norm_chain_id = normalize_chain_id(obs.human_chain_id)
        proto_ns = obs.protocol_namespace or self._default_namespace(obs.stack_family)
        caip2 = obs.caip2 or (format_caip2(proto_ns, norm_chain_id) if norm_chain_id else None)

        chain_product: Optional[ChainProduct] = None
        is_new = False

        # 1. Strongest evidence: a verified genesis fingerprint under this
        #    protocol identity is the same network incarnation (weight 1.00).
        if obs.genesis_fingerprint and caip2:
            chain_product = await self._find_by_genesis(caip2, obs.genesis_fingerprint)

        # 2. CAIP-2 match. Safe only within one organization; across
        #    organizations it is a chain-ID collision, not an identity.
        if chain_product is None and caip2:
            matches = await self._find_all_by_caip2(caip2)
            same_org = [c for c in matches if c.organization_id == org.org_id]
            other_org = [c for c in matches if c.organization_id != org.org_id]

            if same_org:
                chain_product = same_org[0]
            elif other_org:
                # Do not merge. Record the collision against the existing
                # candidate and let a human decide (spec 16).
                for colliding in other_org:
                    await self.open_review_task(
                        "chain_id_collision",
                        reason=(
                            f"CAIP-2 {caip2} is claimed by '{obs.candidate_name}' "
                            f"(org {org.org_id}) and by existing candidate "
                            f"'{colliding.canonical_name}' (org {colliding.organization_id}). "
                            "Chain-ID reuse without an explained migration must be "
                            "reviewed before any merge."
                        ),
                        candidate_id=colliding.id,
                        related_candidate_id=stable_uuid(org.org_id, canonical_slug),
                        match_weight=WEIGHT_SAME_EXPLORER_RPC_HOST_AND_CHAIN_ID,
                        details={"caip2": caip2, "claimed_by": obs.candidate_name},
                        evidence_refs=[evidence_id],
                    )
                    await self._raise_risk_signal(
                        colliding.id,
                        "chain_id_collision",
                        evidence_id,
                        f"CAIP-2 {caip2} claimed by more than one organization",
                    )

        # 3. Deterministic identity within the resolved organization.
        candidate_id = stable_uuid(org.org_id, canonical_slug)
        if chain_product is None:
            chain_product = await self._load_candidate(candidate_id)

        now = datetime.now(timezone.utc)
        if chain_product is None:
            # Before creating, check whether the same normalized name already
            # exists under a *different* organization. That is a 0.40 match:
            # never auto-merged, but worth an analyst's attention.
            await self._flag_weak_name_match(obs, org, candidate_id, evidence_id)

            is_new = True
            chain_product = ChainProduct(
                id=candidate_id,
                organization_id=org.org_id,
                canonical_name=obs.candidate_name,
                slug=canonical_slug,
                aliases=sorted(
                    {obs.candidate_name, normalize_name(obs.candidate_name),
                     strip_legal_suffixes(obs.candidate_name)} - {""}
                ),
                purpose_labels=obs.purpose_labels,
                stack_family=self._enum_value(obs.stack_family),
                stack_details=obs.stack_details,
                layer=obs.layer,
                stage=self._enum_value(obs.stage),
                first_seen_at=now,
            )
            self.session.add(chain_product)
            await self.session.flush()

            # An assessment row exists so the analyst UI always has something
            # to render. It starts at A4 with zero score: the Africa
            # classifier is the only thing allowed to raise it, from evidence.
            self.session.add(
                AfricaAssessment(
                    candidate_id=chain_product.id,
                    intent_label="A4_no_evidence",
                    readiness=0.0,
                    whitespace=0.0,
                    countries=[],
                    regions=[],
                    languages=[],
                    rails_use_cases=[],
                    evidence_ids=[evidence_id],
                    confidence=0.0,
                )
            )
            # No score snapshot is fabricated here. Scores are written only by
            # the scoring engine from actual evidence, so that every score
            # resolves to something (spec 03 "a generated summary cannot
            # become evidence for itself").
            await self.session.flush()
        else:
            self._accumulate_aliases(chain_product, obs)

        await self._resolve_network_and_incarnation(chain_product, obs, evidence_id)
        await self._link_evidence(chain_product.id, evidence_id, is_new)
        await self.session.flush()

        # Re-load with collections eagerly populated. Callers walk
        # `candidate.networks` and `candidate.assessment` straight away, and an
        # async session cannot service a lazy load at attribute-access time.
        reloaded = await self._load_candidate(chain_product.id)
        return (reloaded or chain_product), is_new

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _enum_value(value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value)

    @staticmethod
    def _default_namespace(stack_family: Any) -> str:
        family = stack_family.value if hasattr(stack_family, "value") else str(stack_family)
        return {"evm": "eip155", "cosmos": "cosmos", "svm": "solana", "starknet": "starknet"}.get(
            family, family
        )

    @staticmethod
    def _candidate_loader_options():
        return (
            selectinload(ChainProduct.organization),
            selectinload(ChainProduct.networks).selectinload(Network.incarnations),
            selectinload(ChainProduct.assessment),
            selectinload(ChainProduct.score),
        )

    async def _load_candidate(self, candidate_id: str) -> Optional[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .options(*self._candidate_loader_options())
            .where(ChainProduct.id == candidate_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _find_by_genesis(self, caip2: str, genesis_fingerprint: str) -> Optional[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .join(Network, Network.chain_product_id == ChainProduct.id)
            .join(NetworkIncarnation, NetworkIncarnation.network_id == Network.id)
            .options(*self._candidate_loader_options())
            .where(
                Network.caip2 == caip2,
                NetworkIncarnation.genesis_fingerprint == genesis_fingerprint,
            )
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _find_all_by_caip2(self, caip2: str) -> List[ChainProduct]:
        stmt = (
            select(ChainProduct)
            .join(Network, Network.chain_product_id == ChainProduct.id)
            .options(*self._candidate_loader_options())
            .where(Network.caip2 == caip2)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def _flag_weak_name_match(
        self, obs: RawObservation, org: Organization, new_candidate_id: str, evidence_id: str
    ) -> None:
        """Open a review task when only the normalized name matches (0.40)."""
        norm = normalize_name(obs.candidate_name)
        if not norm:
            return
        stmt = select(ChainProduct).where(ChainProduct.canonical_name.isnot(None))
        stmt = stmt.where(_json_contains(ChainProduct.aliases, norm))
        for other in (await self.session.execute(stmt)).scalars().unique().all():
            if other.organization_id == org.org_id or other.id == new_candidate_id:
                continue
            await self.open_review_task(
                "weak_name_match",
                reason=(
                    f"'{obs.candidate_name}' normalizes to '{norm}', which already exists as "
                    f"'{other.canonical_name}' under a different organization. A name-only "
                    "match is weight 0.40 and must never be auto-merged."
                ),
                candidate_id=other.id,
                related_candidate_id=new_candidate_id,
                match_weight=WEIGHT_NAME_ONLY,
                details={"normalized_name": norm},
                evidence_refs=[evidence_id],
            )

    @staticmethod
    def _accumulate_aliases(chain_product: ChainProduct, obs: RawObservation) -> None:
        new_aliases = {obs.candidate_name, normalize_name(obs.candidate_name)} - {""}
        chain_product.aliases = sorted(set(list(chain_product.aliases) + list(new_aliases)))
        if obs.purpose_labels:
            chain_product.purpose_labels = sorted(
                set(list(chain_product.purpose_labels) + list(obs.purpose_labels))
            )

    async def _link_evidence(self, candidate_id: str, evidence_id: str, is_new: bool) -> None:
        stmt = select(ObservationLink).where(
            ObservationLink.evidence_id == evidence_id,
            ObservationLink.candidate_id == candidate_id,
        )
        if (await self.session.execute(stmt)).scalar_one_or_none():
            return
        self.session.add(
            ObservationLink(
                evidence_id=evidence_id,
                candidate_id=candidate_id,
                link_type="primary_discovery" if is_new else "corroboration",
            )
        )

    async def _resolve_network_and_incarnation(
        self, chain_product: ChainProduct, obs: RawObservation, evidence_id: str
    ) -> None:
        """Resolve the network row and, only on verified genesis, its incarnation."""
        env = self._enum_value(obs.environment)
        proto_ns = obs.protocol_namespace or self._default_namespace(chain_product.stack_family)
        norm_chain_id = normalize_chain_id(obs.human_chain_id)
        caip2 = obs.caip2 or (format_caip2(proto_ns, norm_chain_id) if norm_chain_id else None)

        network_id = stable_uuid(chain_product.id, env, proto_ns)
        stmt = (
            select(Network)
            .options(selectinload(Network.incarnations))
            .where(Network.id == network_id)
        )
        net = (await self.session.execute(stmt)).scalar_one_or_none()

        if net is None:
            net = Network(
                id=network_id,
                chain_product_id=chain_product.id,
                environment=env,
                is_public=obs.is_public,
                caip2=caip2,
                protocol_namespace=proto_ns,
                human_chain_id=norm_chain_id,
                rpc_urls=sorted(set(obs.rpc_urls)),
                explorer_urls=sorted(set(obs.explorer_urls)),
                faucet_urls=sorted(set(obs.faucet_urls)),
                launch_claims=obs.claims,
            )
            self.session.add(net)
            await self.session.flush()
        else:
            net.rpc_urls = sorted(set(list(net.rpc_urls) + list(obs.rpc_urls)))
            net.explorer_urls = sorted(set(list(net.explorer_urls) + list(obs.explorer_urls)))
            net.faucet_urls = sorted(set(list(net.faucet_urls) + list(obs.faucet_urls)))
            if caip2 and not net.caip2:
                net.caip2 = caip2
            if norm_chain_id and not net.human_chain_id:
                net.human_chain_id = norm_chain_id
            elif norm_chain_id and net.human_chain_id != norm_chain_id:
                # The same logical network reporting two different chain IDs is
                # an identity problem, not something to overwrite silently.
                await self.open_review_task(
                    "chain_id_changed",
                    reason=(
                        f"Network {net.id} was recorded with chain ID {net.human_chain_id} "
                        f"but this observation reports {norm_chain_id}."
                    ),
                    candidate_id=chain_product.id,
                    match_weight=WEIGHT_SAME_EXPLORER_RPC_HOST_AND_CHAIN_ID,
                    details={"stored": net.human_chain_id, "observed": norm_chain_id},
                    evidence_refs=[evidence_id],
                )
            if obs.claims:
                merged_claims = dict(net.launch_claims)
                merged_claims.update(obs.claims)
                net.launch_claims = merged_claims

        # Incarnations require a real genesis fingerprint. Without one there is
        # nothing to fingerprint, and a placeholder row would pollute the
        # identity table (spec 04: incarnation_key uses the *verified* genesis).
        if not obs.genesis_fingerprint:
            return

        await self.register_incarnation(
            net,
            genesis_fingerprint=obs.genesis_fingerprint,
            genesis_time=obs.genesis_time,
            evidence_id=evidence_id,
            candidate_id=chain_product.id,
        )

    async def register_incarnation(
        self,
        net: Network,
        *,
        genesis_fingerprint: str,
        genesis_time: Optional[datetime] = None,
        block0_hash: Optional[str] = None,
        evidence_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
    ) -> NetworkIncarnation:
        """Create or return the incarnation for a verified genesis fingerprint.

        A new fingerprint on a network that already has an active one is a
        reset or a collision: the previous incarnation is superseded, the
        history is kept, and an analyst task is opened (spec 16).
        """
        inc_id = stable_uuid(net.id, genesis_fingerprint)
        stmt = select(NetworkIncarnation).where(NetworkIncarnation.id == inc_id)
        inc = (await self.session.execute(stmt)).scalar_one_or_none()
        if inc is not None:
            if genesis_time and not inc.genesis_time:
                inc.genesis_time = genesis_time
            if block0_hash and not inc.block0_hash:
                inc.block0_hash = block0_hash
            return inc

        stmt_prev = select(NetworkIncarnation).where(
            NetworkIncarnation.network_id == net.id,
            NetworkIncarnation.status == IncarnationStatus.ACTIVE.value,
        )
        previous = list((await self.session.execute(stmt_prev)).scalars().all())

        inc = NetworkIncarnation(
            id=inc_id,
            network_id=net.id,
            genesis_fingerprint=genesis_fingerprint,
            genesis_time=genesis_time,
            block0_hash=block0_hash,
            status=IncarnationStatus.ACTIVE.value,
        )
        self.session.add(inc)
        await self.session.flush()

        for prev in previous:
            if prev.genesis_fingerprint == genesis_fingerprint:
                continue
            prev.status = IncarnationStatus.SUPERSEDED.value
            prev.superseded_by_id = inc_id
            if candidate_id:
                await self.open_review_task(
                    "network_reset_or_collision",
                    reason=(
                        f"Network {net.id} changed genesis fingerprint from "
                        f"{prev.genesis_fingerprint} to {genesis_fingerprint}. If this is a "
                        "testnet reset the supersession is correct; if the chain ID was "
                        "reused by a different network it is a collision."
                    ),
                    candidate_id=candidate_id,
                    related_candidate_id=inc_id,
                    match_weight=WEIGHT_EXACT_PROTOCOL_AND_GENESIS,
                    details={
                        "previous_genesis": prev.genesis_fingerprint,
                        "new_genesis": genesis_fingerprint,
                        "chain_id": net.human_chain_id,
                    },
                    evidence_refs=[evidence_id] if evidence_id else [],
                )
                await self._raise_risk_signal(
                    candidate_id,
                    "genesis_changed",
                    evidence_id,
                    "Genesis fingerprint changed on an existing network",
                )
        return inc
