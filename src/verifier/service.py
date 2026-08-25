"""Verification service: persists probe observations and proves liveness (spec 14, 15).

Liveness is a claim about *change over time*, so it cannot be established by a
single request. Two observations 60-180 seconds apart are recorded and then
compared. Both rows are kept: an alert asserting "this chain is advancing" must
be able to show the two heights it was derived from.

The recheck is deliberately not a sleep inside this call. Spec 18 requires it to
be a separate queued job, so `endpoints_due_for_recheck` exposes the work and
the scheduler drives round two.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.types import VerificationResult
from src.storage.models import ChainProduct, Network, NetworkIncarnation, VerificationObservation
from src.util.redaction import endpoint_hash, redact_url
from src.util.timeutil import to_utc, utcnow
from src.verifier.engine import verifier_engine

logger = logging.getLogger(__name__)

# Failure classifications from spec 15. `unreachable` lowers liveness but is
# explicitly *not* evidence of illegitimacy on its own.
FAILURE_UNREACHABLE = "unreachable"
FAILURE_IDENTITY_MISMATCH = "identity_mismatch"
FAILURE_NON_ADVANCING = "non_advancing"
FAILURE_METHOD_UNSUPPORTED = "method_unsupported"
FAILURE_PRIVATE_TARGET = "private_target"
FAILURE_OVERSIZED = "oversized_or_malformed"
FAILURE_RATE_LIMITED = "rate_limited"


@dataclass
class LivenessVerdict:
    """The outcome of comparing two probe observations."""

    live: bool
    advancing: Optional[bool]
    identity_stable: Optional[bool]
    first_height: Optional[int] = None
    second_height: Optional[int] = None
    first_observed_at: Optional[datetime] = None
    second_observed_at: Optional[datetime] = None
    failure_class: Optional[str] = None
    detail: str = ""

    def as_evidence(self) -> Dict[str, Any]:
        """Explainable payload for the evidence card."""
        return {
            "live": self.live,
            "advancing": self.advancing,
            "identity_stable": self.identity_stable,
            "first_height": self.first_height,
            "second_height": self.second_height,
            "first_observed_at": self.first_observed_at.isoformat() if self.first_observed_at else None,
            "second_observed_at": self.second_observed_at.isoformat() if self.second_observed_at else None,
            "failure_class": self.failure_class,
            "detail": self.detail,
        }


def identity_fingerprint(result: VerificationResult) -> Optional[str]:
    """Stable fingerprint of the identity an endpoint served.

    Genesis is included when available because a chain ID alone is reusable;
    the pair is what distinguishes an incarnation (spec 04).
    """
    if not result.identity:
        return None
    parts = [result.identity.protocol_namespace or "", result.identity.chain_id or ""]
    genesis = result.identity.genesis_hash or (result.genesis.genesis_hash if result.genesis else None)
    if genesis:
        parts.append(genesis)
    return ":".join(p for p in parts if p)


class VerificationService:
    """Records read-only probes and derives liveness from stored observations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def probe_and_record(
        self,
        endpoint: str,
        family: str,
        *,
        candidate_id: Optional[str] = None,
        network_id: Optional[str] = None,
        expected_chain_id: Optional[str] = None,
        probe_round: int = 1,
    ) -> Tuple[VerificationResult, VerificationObservation]:
        """Run one read-only probe and persist exactly what was observed."""
        result = await verifier_engine.probe_endpoint(endpoint, family=family)
        fingerprint = identity_fingerprint(result)

        failure_class: Optional[str] = None
        failure_detail: Optional[str] = result.error_detail
        success = result.success

        if not success:
            failure_class = {
                "private_target": FAILURE_PRIVATE_TARGET,
                "method_unsupported": FAILURE_METHOD_UNSUPPORTED,
                "rate_limited": FAILURE_RATE_LIMITED,
                "oversized/malformed": FAILURE_OVERSIZED,
            }.get(result.error_type or "", FAILURE_UNREACHABLE)
        elif expected_chain_id and result.identity and result.identity.chain_id:
            if str(result.identity.chain_id) != str(expected_chain_id):
                # The endpoint served a different network than the one the
                # candidate publishes. High-priority risk flag (spec 15).
                success = False
                failure_class = FAILURE_IDENTITY_MISMATCH
                failure_detail = (
                    f"published chain ID {expected_chain_id} but endpoint reported "
                    f"{result.identity.chain_id}"
                )

        observation = VerificationObservation(
            candidate_id=candidate_id,
            network_id=network_id,
            # Never store the raw URL: RPC endpoints routinely embed API keys.
            endpoint=redact_url(endpoint),
            endpoint_hash=endpoint_hash(endpoint),
            family=family,
            probe_round=probe_round,
            success=success,
            failure_class=failure_class,
            failure_detail=(failure_detail or "")[:2000] or None,
            identity_fingerprint=fingerprint,
            chain_id=result.identity.chain_id if result.identity else None,
            genesis_hash=(
                result.identity.genesis_hash
                if result.identity and result.identity.genesis_hash
                else (result.genesis.genesis_hash if result.genesis else None)
            ),
            block_height=result.head.block_height if result.head else None,
            client_version=(result.identity.client_version if result.identity else None),
            raw_observation={
                "error_type": result.error_type,
                "checked_at": result.checked_at.isoformat(),
                "spec_version": result.identity.spec_version if result.identity else None,
            },
            observed_at=result.checked_at,
        )
        self.session.add(observation)
        await self.session.flush()
        return result, observation

    async def recent_observations(
        self, endpoint_hash_value: str, limit: int = 2
    ) -> List[VerificationObservation]:
        stmt = (
            select(VerificationObservation)
            .where(VerificationObservation.endpoint_hash == endpoint_hash_value)
            .order_by(VerificationObservation.observed_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def evaluate_liveness(self, endpoint: str) -> LivenessVerdict:
        """Compare the two most recent observations for an endpoint."""
        observations = await self.recent_observations(endpoint_hash(endpoint), limit=2)
        if len(observations) < 2:
            return LivenessVerdict(
                live=False,
                advancing=None,
                identity_stable=None,
                detail="Awaiting the scheduled second observation.",
            )

        newer, older = observations[0], observations[1]
        if not (newer.success and older.success):
            return LivenessVerdict(
                live=False,
                advancing=None,
                identity_stable=None,
                failure_class=newer.failure_class or older.failure_class or FAILURE_UNREACHABLE,
                detail="At least one observation in the pair failed.",
                first_height=older.block_height,
                second_height=newer.block_height,
                first_observed_at=to_utc(older.observed_at),
                second_observed_at=to_utc(newer.observed_at),
            )

        if newer.block_height is None or older.block_height is None:
            return LivenessVerdict(
                live=False,
                advancing=None,
                identity_stable=None,
                failure_class=FAILURE_METHOD_UNSUPPORTED,
                detail="Endpoint did not report a comparable height.",
            )

        advancing = newer.block_height > older.block_height

        # Fail closed: a missing fingerprint is unknown identity, not stable
        # identity. Treating unknown as stable would let an endpoint that stops
        # reporting its chain ID silently keep a 'verified' badge.
        if newer.identity_fingerprint and older.identity_fingerprint:
            identity_stable = newer.identity_fingerprint == older.identity_fingerprint
        else:
            identity_stable = False

        failure_class = None
        detail = "Height advanced with a stable identity."
        if not advancing:
            failure_class = FAILURE_NON_ADVANCING
            detail = (
                f"Height unchanged across observations ({older.block_height} -> "
                f"{newer.block_height}); watch and retry."
            )
        elif not identity_stable:
            failure_class = FAILURE_IDENTITY_MISMATCH
            detail = "Endpoint identity changed or was not reported between observations."

        return LivenessVerdict(
            live=bool(advancing and identity_stable),
            advancing=advancing,
            identity_stable=identity_stable,
            first_height=older.block_height,
            second_height=newer.block_height,
            first_observed_at=to_utc(older.observed_at),
            second_observed_at=to_utc(newer.observed_at),
            failure_class=failure_class,
            detail=detail,
        )

    async def endpoints_due_for_recheck(self, limit: int = 50) -> List[VerificationObservation]:
        """First-round observations old enough for their scheduled second probe.

        The window is the spec's 60-180 seconds. Anything older than the upper
        bound is also returned so a missed scheduler tick does not strand a
        candidate without a liveness verdict.
        """
        now = utcnow()
        earliest = now - timedelta(seconds=settings.VERIFY.liveness_recheck_min_seconds)
        stmt = (
            select(VerificationObservation)
            .where(
                VerificationObservation.probe_round == 1,
                VerificationObservation.success.is_(True),
                VerificationObservation.observed_at <= earliest,
            )
            .order_by(VerificationObservation.observed_at.asc())
            .limit(limit)
        )
        candidates = list((await self.session.execute(stmt)).scalars().all())

        due: List[VerificationObservation] = []
        for observation in candidates:
            existing = await self.recent_observations(observation.endpoint_hash, limit=2)
            if len(existing) < 2:
                due.append(observation)
        return due

    async def apply_verified_identity(
        self,
        network: Network,
        result: VerificationResult,
        verdict: Optional[LivenessVerdict] = None,
    ) -> Optional[NetworkIncarnation]:
        """Record a verified genesis fingerprint against its network.

        Only a genesis actually returned by the endpoint reaches the
        incarnation table; there is no placeholder path.
        """
        genesis = None
        if result.identity and result.identity.genesis_hash:
            genesis = result.identity.genesis_hash
        elif result.genesis and result.genesis.genesis_hash:
            genesis = result.genesis.genesis_hash
        if not genesis:
            return None

        from src.core.resolver import EntityResolver  # local import avoids a cycle

        resolver = EntityResolver(self.session)
        incarnation = await resolver.register_incarnation(
            network,
            genesis_fingerprint=genesis,
            genesis_time=(result.genesis.genesis_time if result.genesis else None),
            block0_hash=(result.genesis.block0_hash if result.genesis else None),
            candidate_id=network.chain_product_id,
        )
        incarnation.last_verified_at = result.checked_at
        if result.head:
            incarnation.last_observed_height = result.head.block_height
            if incarnation.first_observed_height is None:
                incarnation.first_observed_height = result.head.block_height
        if verdict and verdict.live:
            incarnation.status = incarnation.status or "active"
        return incarnation
