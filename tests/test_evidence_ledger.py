"""Append-only evidence ledger and score history (spec 03, 20, 21)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.core.pipeline import IntelligencePipeline
from src.core.resolver import EntityResolver
from src.core.types import NetworkEnvironment, RawItem, RawObservation, StackFamily
from src.storage.models import EvidenceEvent, ScoreSnapshot
from src.storage.repository import Repository
from src.util.timeutil import observed_bucket

NOW = datetime.now(timezone.utc)


def _raw(external_id: str, content_hash: str, observed_at: datetime, url: str = "https://x.invalid/a"):
    return RawItem(
        source_id="ethereum_lists",
        external_id=external_id,
        url=url,
        source_family="registry",
        raw_payload={"k": "v"},
        content_hash=content_hash,
        observed_at=observed_at,
    )


@pytest.mark.asyncio
async def test_replay_of_the_same_event_is_idempotent(test_db):
    """Acceptance test 10: a replayed event must not duplicate evidence."""
    repo = Repository(test_db)
    first = await repo.append_evidence(_raw("pr-1", "hash-a", NOW))
    for _ in range(5):
        again = await repo.append_evidence(_raw("pr-1", "hash-a", NOW))
        assert again.id == first.id

    count = await test_db.scalar(
        select(func.count()).select_from(EvidenceEvent).where(EvidenceEvent.external_id == "pr-1")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_identical_content_in_the_same_bucket_is_one_row(test_db):
    repo = Repository(test_db)
    first = await repo.append_evidence(_raw("pr-a", "same-hash", NOW))
    second = await repo.append_evidence(_raw("pr-b", "same-hash", NOW + timedelta(seconds=30)))
    assert second.id == first.id, "same bytes inside one bucket is the same observation"


@pytest.mark.asyncio
async def test_identical_content_in_a_later_bucket_is_a_new_observation(test_db):
    """Unchanged content seen later is a genuine re-observation.

    The two-column key (source_id, content_hash) would swallow this forever,
    freezing freshness and making a liveness re-check unrecordable. The bucket
    is the third column that keeps re-observation meaningful.
    """
    repo = Repository(test_db)
    bucket_minutes = settings.VERIFY_EVIDENCE_BUCKET_MINUTES
    later = NOW + timedelta(minutes=bucket_minutes * 2)

    first = await repo.append_evidence(_raw("pr-x", "stable-hash", NOW))
    second = await repo.append_evidence(_raw("pr-y", "stable-hash", later))

    assert second.id != first.id
    assert first.observed_bucket != second.observed_bucket
    assert first.observed_bucket == observed_bucket(NOW, minutes=bucket_minutes)


@pytest.mark.asyncio
async def test_evidence_urls_are_stored_redacted(test_db):
    """Source URLs can embed provider keys; evidence must not carry them."""
    repo = Repository(test_db)
    evidence = await repo.append_evidence(
        _raw("pr-secret", "hash-secret", NOW, url="https://api.example.com/v2/KEY1234567890abcdefghijkl?token=abc")
    )
    assert "KEY1234567890abcdefghijkl" not in evidence.url
    assert "token=abc" not in evidence.url


@pytest.mark.asyncio
async def test_rescoring_appends_history_and_moves_the_current_pointer(test_db):
    """Old snapshots stay readable so calibration and audit can replay them."""
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)
    pipeline = IntelligencePipeline(test_db)

    evidence = await repo.append_evidence(_raw("hist-1", "hash-hist", NOW))
    candidate, _ = await resolver.upsert_candidate(
        RawObservation(
            candidate_name="History Chain",
            organization_name="History Labs",
            organization_domains=["history.dev"],
            stack_family=StackFamily.EVM,
            environment=NetworkEnvironment.TESTNET,
            human_chain_id="31337",
            reliability=0.9,
        ),
        evidence.id,
    )

    first = await pipeline.rescore_candidate(candidate, trigger_alerts=False)
    second = await pipeline.rescore_candidate(candidate, trigger_alerts=False)

    assert first.id != second.id, "a rescore appends a snapshot, it does not mutate one"
    assert candidate.current_score_id == second.id

    snapshots = (
        await test_db.execute(
            select(ScoreSnapshot).where(ScoreSnapshot.candidate_id == candidate.id)
        )
    ).scalars().all()
    assert len(snapshots) == 2

    # Every snapshot records the config version that produced it.
    assert all(s.rule_version == settings.RULE_VERSION for s in snapshots)


@pytest.mark.asyncio
async def test_scores_are_never_fabricated_at_candidate_creation(test_db):
    """A candidate starts with no score at all rather than an invented one.

    Spec 03: a generated value cannot become evidence for itself. Seeding a
    placeholder confidence would put an unexplainable number in the queue.
    """
    repo = Repository(test_db)
    resolver = EntityResolver(test_db)

    evidence = await repo.append_evidence(_raw("fresh-1", "hash-fresh", NOW))
    candidate, is_new = await resolver.upsert_candidate(
        RawObservation(
            candidate_name="Unscored Chain",
            organization_domains=["unscored.dev"],
            stack_family=StackFamily.EVM,
            human_chain_id="4747",
        ),
        evidence.id,
    )
    assert is_new is True
    assert candidate.current_score_id is None

    count = await test_db.scalar(
        select(func.count()).select_from(ScoreSnapshot).where(
            ScoreSnapshot.candidate_id == candidate.id
        )
    )
    assert count == 0

    # The Africa assessment exists but starts at "no evidence" with zero score.
    assert candidate.assessment.intent_label == "A4_no_evidence"
    assert candidate.assessment.total_score == 0.0
