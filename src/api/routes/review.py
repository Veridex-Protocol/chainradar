"""Analyst review queue, score history, verification trail and suppression.

These endpoints exist because the engine deliberately refuses to decide some
things on its own (spec 16) and must be able to show its working for the ones
it does decide (spec 22).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.database import get_db_session
from src.storage.models import (
    AlertDispatch,
    AuditLog,
    ChainProduct,
    Contact,
    ReviewTask,
    ScoreSnapshot,
    VerificationObservation,
)
from src.util.redaction import channel_hash
from src.util.timeutil import isoformat, to_wat, utcnow

router = APIRouter(tags=["review"])


class ResolveTaskRequest(BaseModel):
    resolution: str = Field(..., description="merge | keep_separate | not_a_collision | dismissed")
    actor: str = "analyst"
    reason: Optional[str] = None


class SuppressContactRequest(BaseModel):
    channel_value: str = Field(..., description="Email, form URL or handle to suppress")
    reason: str = "Opt-out / privacy request"
    actor: str = "analyst"


def _task_payload(task: ReviewTask) -> Dict[str, Any]:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "candidate_id": task.candidate_id,
        "related_candidate_id": task.related_candidate_id or None,
        "match_weight": task.match_weight,
        "reason": task.reason,
        "details": task.details,
        "evidence_refs": task.evidence_refs,
        "status": task.status,
        "resolution": task.resolution,
        "resolved_by": task.resolved_by,
        "created_at": isoformat(task.created_at),
        "created_at_wat": to_wat(task.created_at).strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/review_tasks")
async def list_review_tasks(
    status: str = Query("open", description="open | resolved | all"),
    task_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Decisions the engine escalated rather than making automatically."""
    stmt = select(ReviewTask)
    if status != "all":
        stmt = stmt.where(ReviewTask.status == status)
    if task_type:
        stmt = stmt.where(ReviewTask.task_type == task_type)

    total = await db.scalar(
        select(func.count()).select_from(stmt.subquery())
    )
    stmt = stmt.order_by(desc(ReviewTask.created_at)).limit(limit).offset(offset)
    tasks = (await db.execute(stmt)).scalars().all()

    by_type_stmt = (
        select(ReviewTask.task_type, func.count())
        .where(ReviewTask.status == "open")
        .group_by(ReviewTask.task_type)
    )
    by_type = {t: c for t, c in (await db.execute(by_type_stmt)).all()}

    return {
        "total": total or 0,
        "open_by_type": by_type,
        "tasks": [_task_payload(t) for t in tasks],
    }


@router.post("/review_tasks/{task_id}/resolve")
async def resolve_review_task(
    task_id: str,
    payload: ResolveTaskRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Close a review task, recording who decided and why (spec 20, 23)."""
    task = await db.get(ReviewTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Review task not found")
    if task.status == "resolved":
        raise HTTPException(status_code=409, detail="Review task is already resolved")

    before = {"status": task.status, "resolution": task.resolution}
    task.status = "resolved"
    task.resolution = payload.resolution
    task.resolved_by = payload.actor
    task.resolved_at = utcnow()

    # Analyst decisions are audited; they never edit the raw evidence.
    db.add(
        AuditLog(
            actor=payload.actor,
            action="resolve_review_task",
            target_type="review_task",
            target_id=task.id,
            before_state=before,
            after_state={"status": task.status, "resolution": task.resolution},
            reason=payload.reason,
        )
    )
    await db.flush()
    return _task_payload(task)


@router.get("/candidates/{candidate_id}/score_history")
async def score_history(
    candidate_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Every score this candidate has ever had, newest first.

    Snapshots are appended rather than overwritten, so a threshold change or a
    new piece of evidence can be traced to the exact moment it moved a score.
    """
    candidate = await db.get(ChainProduct, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    stmt = (
        select(ScoreSnapshot)
        .where(ScoreSnapshot.candidate_id == candidate_id)
        .order_by(desc(ScoreSnapshot.calculated_at))
        .limit(limit)
    )
    snapshots = (await db.execute(stmt)).scalars().all()

    return {
        "candidate_id": candidate_id,
        "current_score_id": candidate.current_score_id,
        "snapshots": [
            {
                "id": s.id,
                "state": s.state,
                "workflow_state": s.workflow_state,
                "confidence": s.confidence,
                "momentum": s.momentum,
                "africa_fit": s.africa_fit,
                "risk": s.risk,
                "radar_score": s.radar_score,
                "outreach_score": s.outreach_score,
                "outreach_qualified": s.outreach_qualified,
                "rule_version": s.rule_version,
                "feature_vector": s.feature_vector,
                "calculated_at": isoformat(s.calculated_at),
                "is_current": s.id == candidate.current_score_id,
            }
            for s in snapshots
        ],
    }


@router.get("/candidates/{candidate_id}/verifications")
async def verification_trail(
    candidate_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Raw probe observations behind any liveness claim (spec 14).

    Endpoints are stored redacted, so this is safe to expose to an analyst
    without leaking a provider API key.
    """
    stmt = (
        select(VerificationObservation)
        .where(VerificationObservation.candidate_id == candidate_id)
        .order_by(desc(VerificationObservation.observed_at))
        .limit(limit)
    )
    observations = (await db.execute(stmt)).scalars().all()
    return {
        "candidate_id": candidate_id,
        "observations": [
            {
                "id": o.id,
                "endpoint": o.endpoint,
                "family": o.family,
                "probe_round": o.probe_round,
                "success": o.success,
                "failure_class": o.failure_class,
                "failure_detail": o.failure_detail,
                "chain_id": o.chain_id,
                "genesis_hash": o.genesis_hash,
                "block_height": o.block_height,
                "identity_fingerprint": o.identity_fingerprint,
                "client_version": o.client_version,
                "observed_at": isoformat(o.observed_at),
            }
            for o in observations
        ],
    }


@router.get("/alerts")
async def list_alerts(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Alerts actually dispatched, including suppressed duplicates."""
    stmt = select(AlertDispatch).order_by(desc(AlertDispatch.dispatched_at)).limit(limit)
    alerts = (await db.execute(stmt)).scalars().all()
    return {
        "alerts": [
            {
                "id": a.id,
                "candidate_id": a.candidate_id,
                "alert_type": a.alert_type,
                "state": a.state,
                "channel": a.channel,
                "delivered": a.delivered,
                "delivery_detail": a.delivery_detail,
                "dispatched_at": isoformat(a.dispatched_at),
                "dispatched_at_wat": to_wat(a.dispatched_at).strftime("%Y-%m-%d %H:%M"),
            }
            for a in alerts
        ]
    }


@router.post("/contacts/suppress")
async def suppress_contact(
    payload: SuppressContactRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Honour an opt-out or data-subject request (spec 23, 27).

    Suppression is keyed on the hashed channel so it survives re-ingestion: a
    source republishing the address must never bring it back into outreach.
    """
    digest = channel_hash(payload.channel_value)
    stmt = select(Contact).where(Contact.channel_hash == digest)
    contacts = (await db.execute(stmt)).scalars().all()

    for contact in contacts:
        contact.suppressed = True
        contact.suppression_reason = payload.reason

    db.add(
        AuditLog(
            actor=payload.actor,
            action="suppress_contact",
            target_type="contact_channel",
            # Only the hash is audited; the raw address is not duplicated into
            # the audit trail (data minimization).
            target_id=digest,
            after_state={"suppressed": True, "matched_rows": len(contacts)},
            reason=payload.reason,
        )
    )
    await db.flush()
    return {"channel_hash": digest, "suppressed_rows": len(contacts), "reason": payload.reason}
