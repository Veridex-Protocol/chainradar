"""Entity resolution, collisions, resets and liveness (spec 14, 16).

These exercise the behaviours the engine must get right to avoid merging two
unrelated projects or claiming a dead chain is live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.core.resolver import EntityResolver
from src.core.types import (
    IncarnationStatus,
    NetworkEnvironment,
    RawItem,
    RawObservation,
    StackFamily,
)
from src.storage.models import (
    ChainProduct,
    Network,
    NetworkIncarnation,
    Organization,
    ReviewTask,
    ScoreSnapshot,
    Signal,
    VerificationObservation,
)
from src.storage.repository import Repository
from src.util.redaction import endpoint_hash
from src.verifier.service import VerificationService

NOW = datetime.now(timezone.utc)


def _raw(source_id: str, external_id: str, family: str = "registry", observed_at=None) -> RawItem:
    return RawItem(
        source_id=source_id,
        external_id=external_id,
        url="https://github.com/ethereum-lists/chains/pull/1",
        source_family=family,
        raw_payload={"external_id": external_id},
        content_hash=f"hash-{external_id}",
        observed_at=observed_at or NOW,
    )


def _obs(name: str, chain_id: str, *, genesis=None, domains=(), github=()) -> RawObservation:
    return RawObservation(
        candidate_name=name,
        organization_name=name,
        organization_domains=list(domains),
        github_orgs=list(github),
        stack_family=StackFamily.EVM,
        environment=NetworkEnvironment.TESTNET,
        human_chain_id=chain_id,
        genesis_fingerprint=genesis,
        reliability=0.9,
    )


# --------------------------------------------------------------------------
# Chain-ID collisions
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_chain_id_different_orgs_never_auto_merges(test_db):
    """Acceptance test 5: separate incarnations plus a hard risk flag.

    Two unrelated projects claiming EVM chain ID 987654 is a collision, not an
    identity. Merging them would fabricate a single candidate out of two real
    organizations - the exact failure spec 16 forbids.
    """
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev1 = await repo.append_evidence(_raw("ethereum_lists", "collide-1"))
    first, _ = await resolver.upsert_candidate(
        _obs("Kora Network", "987654", genesis="0xaaa", domains=["kora.network"]), ev1.id
    )

    ev2 = await repo.append_evidence(_raw("chainid_network", "collide-2"))
    second, _ = await resolver.upsert_candidate(
        _obs("Zephyr Chain", "987654", genesis="0xbbb", domains=["zephyr.xyz"]), ev2.id
    )

    assert first.id != second.id, "colliding chain IDs must stay separate candidates"
    assert first.organization_id != second.organization_id

    tasks = (
        await test_db.execute(select(ReviewTask).where(ReviewTask.task_type == "chain_id_collision"))
    ).scalars().all()
    assert tasks, "a chain-ID collision must open an analyst review task"
    assert "987654" in tasks[0].reason

    signals = (
        await test_db.execute(
            select(Signal).where(Signal.signal_type == "chain_id_collision")
        )
    ).scalars().all()
    assert signals, "the collision must raise a risk signal the scorer can see"
    assert signals[0].polarity == "negative"


@pytest.mark.asyncio
async def test_repeated_collision_does_not_spawn_duplicate_tasks(test_db):
    """Re-observing the same collision every 10 minutes must not flood the queue."""
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev1 = await repo.append_evidence(_raw("ethereum_lists", "dup-1"))
    await resolver.upsert_candidate(_obs("Alpha Chain", "4242", domains=["alpha.io"]), ev1.id)

    for i in range(3):
        ev = await repo.append_evidence(_raw("chainid_network", f"dup-other-{i}"))
        await resolver.upsert_candidate(_obs("Beta Chain", "4242", domains=["beta.io"]), ev.id)

    tasks = (
        await test_db.execute(select(ReviewTask).where(ReviewTask.task_type == "chain_id_collision"))
    ).scalars().all()
    # Once the second candidate exists, later observations resolve straight to
    # it, so the collision is recorded exactly once rather than on every poll.
    assert len(tasks) == 1, f"expected one open task, got {len(tasks)}"
    assert tasks[0].status == "open"


@pytest.mark.asyncio
async def test_open_review_task_is_idempotent_and_accumulates_evidence(test_db):
    """Re-raising the same task merges evidence instead of duplicating the row."""
    resolver = EntityResolver(test_db)
    first = await resolver.open_review_task(
        "identity_mismatch", reason="endpoint served a different chain ID",
        candidate_id=None, evidence_refs=["ev-1"],
    )
    second = await resolver.open_review_task(
        "identity_mismatch", reason="endpoint served a different chain ID again",
        candidate_id=None, evidence_refs=["ev-2"],
    )
    assert first.id == second.id
    assert set(second.evidence_refs) == {"ev-1", "ev-2"}

    rows = (
        await test_db.execute(
            select(ReviewTask).where(ReviewTask.task_type == "identity_mismatch")
        )
    ).scalars().all()
    assert len(rows) == 1


# --------------------------------------------------------------------------
# Testnet resets
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_testnet_reset_supersedes_and_preserves_history(test_db):
    """Acceptance test 6: old incarnation superseded, history preserved."""
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev1 = await repo.append_evidence(_raw("ethereum_lists", "reset-1"))
    candidate, _ = await resolver.upsert_candidate(
        _obs("Reset Chain", "7777", genesis="0xgenesis_v1", domains=["reset.dev"]), ev1.id
    )

    ev2 = await repo.append_evidence(_raw("ethereum_lists", "reset-2"))
    candidate, _ = await resolver.upsert_candidate(
        _obs("Reset Chain", "7777", genesis="0xgenesis_v2", domains=["reset.dev"]), ev2.id
    )

    incarnations = (
        await test_db.execute(
            select(NetworkIncarnation).where(
                NetworkIncarnation.network_id == candidate.networks[0].id
            )
        )
    ).scalars().all()

    assert len(incarnations) == 2, "the previous incarnation must be retained, not overwritten"
    statuses = {i.status for i in incarnations}
    assert statuses == {IncarnationStatus.ACTIVE.value, IncarnationStatus.SUPERSEDED.value}

    superseded = next(i for i in incarnations if i.status == IncarnationStatus.SUPERSEDED.value)
    active = next(i for i in incarnations if i.status == IncarnationStatus.ACTIVE.value)
    assert superseded.genesis_fingerprint == "0xgenesis_v1"
    assert active.genesis_fingerprint == "0xgenesis_v2"
    assert superseded.superseded_by_id == active.id, "supersession must be linked, not implied"


@pytest.mark.asyncio
async def test_no_incarnation_is_created_without_a_verified_genesis(test_db):
    """The incarnation table holds technical identity, so placeholders are banned.

    A registry entry with no genesis yet is a network, not an incarnation.
    Writing a synthetic fingerprint would corrupt the one table whose purpose
    is to prove which network an observation belongs to.
    """
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev = await repo.append_evidence(_raw("ethereum_lists", "no-genesis"))
    candidate, _ = await resolver.upsert_candidate(
        _obs("Pending Chain", "5150", domains=["pending.dev"]), ev.id
    )

    incarnations = (
        await test_db.execute(
            select(NetworkIncarnation).where(
                NetworkIncarnation.network_id == candidate.networks[0].id
            )
        )
    ).scalars().all()
    assert incarnations == [], "no genesis observed yet means no incarnation row"

    # Once a genesis is verified, the incarnation appears normally.
    ev2 = await repo.append_evidence(_raw("ethereum_lists", "now-genesis"))
    candidate, _ = await resolver.upsert_candidate(
        _obs("Pending Chain", "5150", genesis="0xreal", domains=["pending.dev"]), ev2.id
    )
    incarnations = (
        await test_db.execute(
            select(NetworkIncarnation).where(
                NetworkIncarnation.network_id == candidate.networks[0].id
            )
        )
    ).scalars().all()
    assert len(incarnations) == 1
    assert incarnations[0].genesis_fingerprint == "0xreal"


# --------------------------------------------------------------------------
# Weak matches
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_name_only_match_opens_review_instead_of_merging(test_db):
    """Weight 0.40 never auto-merges (spec 16)."""
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev1 = await repo.append_evidence(_raw("ethereum_lists", "name-1"))
    first, _ = await resolver.upsert_candidate(
        _obs("Meridian", "111", domains=["meridian.one"]), ev1.id
    )
    ev2 = await repo.append_evidence(_raw("github_search", "name-2", family="code_search"))
    second, _ = await resolver.upsert_candidate(
        _obs("Meridian", "222", domains=["meridian-labs.dev"]), ev2.id
    )

    assert first.id != second.id, "identical names under different orgs must not merge"
    tasks = (
        await test_db.execute(select(ReviewTask).where(ReviewTask.task_type == "weak_name_match"))
    ).scalars().all()
    assert tasks and tasks[0].match_weight == 0.40


@pytest.mark.asyncio
async def test_organization_lookup_uses_indexed_containment(test_db):
    """The same domain resolves to one organization across sources."""
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    ev1 = await repo.append_evidence(_raw("ethereum_lists", "org-1"))
    first, _ = await resolver.upsert_candidate(
        _obs("Kora Testnet", "900", domains=["kora.network"], github=["kora-labs"]), ev1.id
    )
    ev2 = await repo.append_evidence(_raw("rss", "org-2", family="official_web"))
    second, _ = await resolver.upsert_candidate(
        _obs("Kora Mainnet", "901", domains=["kora.network"]), ev2.id
    )

    assert first.organization_id == second.organization_id
    org = (
        await test_db.execute(
            select(Organization).where(Organization.org_id == first.organization_id)
        )
    ).scalar_one()
    assert "kora.network" in org.official_domains
    assert "kora-labs" in org.github_orgs


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_liveness_requires_two_persisted_observations(test_db):
    """Spec 14: both observations are stored and compared, never inferred."""
    service = VerificationService(test_db)
    endpoint = "https://rpc.example.invalid/v1"

    verdict = await service.evaluate_liveness(endpoint)
    assert verdict.live is False
    assert "second observation" in verdict.detail

    digest = endpoint_hash(endpoint)
    test_db.add_all([
        VerificationObservation(
            endpoint="https://rpc.example.invalid/v1", endpoint_hash=digest, family="evm",
            probe_round=1, success=True, identity_fingerprint="eip155:900:0xg",
            block_height=100, observed_at=NOW - timedelta(seconds=120),
        ),
        VerificationObservation(
            endpoint="https://rpc.example.invalid/v1", endpoint_hash=digest, family="evm",
            probe_round=2, success=True, identity_fingerprint="eip155:900:0xg",
            block_height=140, observed_at=NOW,
        ),
    ])
    await test_db.flush()

    verdict = await service.evaluate_liveness(endpoint)
    assert verdict.live is True
    assert verdict.advancing is True and verdict.identity_stable is True
    # The verdict must show its working for the evidence card.
    assert verdict.first_height == 100 and verdict.second_height == 140


@pytest.mark.asyncio
async def test_non_advancing_height_is_not_live(test_db):
    service = VerificationService(test_db)
    endpoint = "https://stalled.example.invalid/rpc"
    digest = endpoint_hash(endpoint)
    test_db.add_all([
        VerificationObservation(
            endpoint=endpoint, endpoint_hash=digest, family="evm", probe_round=1, success=True,
            identity_fingerprint="eip155:5:0xg", block_height=42,
            observed_at=NOW - timedelta(seconds=120),
        ),
        VerificationObservation(
            endpoint=endpoint, endpoint_hash=digest, family="evm", probe_round=2, success=True,
            identity_fingerprint="eip155:5:0xg", block_height=42, observed_at=NOW,
        ),
    ])
    await test_db.flush()

    verdict = await service.evaluate_liveness(endpoint)
    assert verdict.live is False
    assert verdict.failure_class == "non_advancing"


@pytest.mark.asyncio
async def test_missing_fingerprint_fails_closed(test_db):
    """Unknown identity is not stable identity."""
    service = VerificationService(test_db)
    endpoint = "https://anon.example.invalid/rpc"
    digest = endpoint_hash(endpoint)
    test_db.add_all([
        VerificationObservation(
            endpoint=endpoint, endpoint_hash=digest, family="evm", probe_round=1, success=True,
            identity_fingerprint=None, block_height=10, observed_at=NOW - timedelta(seconds=120),
        ),
        VerificationObservation(
            endpoint=endpoint, endpoint_hash=digest, family="evm", probe_round=2, success=True,
            identity_fingerprint=None, block_height=20, observed_at=NOW,
        ),
    ])
    await test_db.flush()

    verdict = await service.evaluate_liveness(endpoint)
    assert verdict.identity_stable is False
    assert verdict.live is False


@pytest.mark.asyncio
async def test_verification_observations_never_store_endpoint_secrets(test_db):
    """RPC URLs frequently embed provider API keys (spec 15)."""
    from src.util.redaction import redact_url

    stored = redact_url("https://rpc.example.com/v2/abcdefghijklmnopqrstuvwxyz123456?apikey=secret")
    assert "abcdefghijklmnopqrstuvwxyz123456" not in stored
    assert "secret" not in stored
    assert "<redacted>" in stored
