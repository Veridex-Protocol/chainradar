"""FastAPI routes for Candidate management and analyst workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.alerting.evidence_card import EvidenceCardBuilder
from src.classifiers.africa import africa_classifier
from src.core.types import CandidateState, WorkflowState
from src.scoring.engine import scoring_engine
from src.storage.database import get_db_session
from src.storage.models import AfricaAssessment, AuditLog, ChainProduct
from src.storage.repository import Repository
from src.util.timeutil import parse_funding_date_filter, parse_iso
from src.verifier.engine import verifier_engine

router = APIRouter(prefix="/candidates", tags=["candidates"])


class WorkflowTransitionRequest(BaseModel):
    workflow_state: str
    actor: str = "analyst"
    reason: Optional[str] = None


class AfricaOverrideRequest(BaseModel):
    intent_label: str
    actor: str = "analyst"
    reason: str
    manual_score: Optional[float] = None
    countries: Optional[List[str]] = None


@router.get("")
async def list_candidates(
    state: Optional[str] = Query(None, description="HOT, QUALIFIED, RADAR, STALE, REJECT"),
    workflow_state: Optional[str] = Query(None),
    africa_intent: Optional[str] = Query(None),
    stack_family: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    has_funding: Optional[bool] = Query(None, description="Filter candidates with or without funding rounds"),
    recent_funding: Optional[bool] = Query(None, description="Filter for chains with verified funding from Q3 2025 to date.now"),
    funding_since: Optional[str] = Query(None, description="ISO timestamp or preset (e.g. 2025-07-01, q3_2025)"),
    funding_until: Optional[str] = Query(None, description="ISO timestamp"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)

    # Parse date filters
    parsed_since = None
    parsed_until = None
    if funding_since:
        parsed_since, parsed_until = parse_funding_date_filter(funding_since)
    if funding_until:
        parsed_until = parse_iso(funding_until)

    candidates = await repo.list_candidates(
        state=state,
        workflow_state=workflow_state,
        africa_intent=africa_intent,
        stack_family=stack_family,
        search_query=q,
        limit=limit,
        offset=offset,
        has_funding=has_funding,
        recent_funding_only=bool(recent_funding),
        funding_since=parsed_since,
        funding_until=parsed_until,
    )

    results = []
    for c in candidates:
        rounds = c.funding_rounds or []
        latest_round = max(rounds, key=lambda r: r.announced_at or datetime.min.replace(tzinfo=timezone.utc)) if rounds else None
        total_usd = sum(float(r.amount_usd) for r in rounds if r.amount_usd)

        results.append({
            "id": c.id,
            "name": c.canonical_name,
            "slug": c.slug,
            "organization": c.organization.display_name if c.organization else None,
            "stage": c.stage,
            "stack_family": c.stack_family,
            "layer": c.layer,
            "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None,
            "last_verified_at": c.last_verified_at.isoformat() if c.last_verified_at else None,
            "africa_label": c.assessment.intent_label if c.assessment else "A4_no_evidence",
            "africa_score": c.assessment.total_score if c.assessment else 0.0,
            "africa_countries": c.assessment.countries if c.assessment else [],
            "funding_rounds_count": len(rounds),
            "total_funding_usd": total_usd,
            "latest_funding": {
                "round_type": latest_round.round_type,
                "amount_usd": latest_round.amount_usd,
                "amount_as_published": latest_round.amount_as_published,
                "lead_investor": latest_round.lead_investor,
                "announced_at": latest_round.announced_at.isoformat() if latest_round.announced_at else None,
            } if latest_round else None,
            "scores": {
                "confidence": c.score.confidence if c.score else 0.0,
                "momentum": c.score.momentum if c.score else 0.0,
                "africa_fit": c.score.africa_fit if c.score else 0.0,
                "risk": c.score.risk if c.score else 0.0,
                "radar_score": c.score.radar_score if c.score else 0.0,
                "outreach_score": c.score.outreach_score if c.score else 0.0,
                "state": c.score.state if c.score else "RADAR",
                "workflow_state": c.score.workflow_state if c.score else "NEW",
            },
        })

    return {"total": len(results), "items": results}


@router.get("/{candidate_id}")
async def get_candidate_details(
    candidate_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)
    candidate = await repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate chain not found.")

    evidence_list = await repo.list_evidence_for_candidate(candidate_id)
    card = EvidenceCardBuilder.build_card(candidate, evidence_list)
    return {
        "candidate": card,
        "raw_evidence_count": len(evidence_list),
    }


@router.get("/{candidate_id}/evidence_card")
async def get_evidence_card(
    candidate_id: str,
    format: str = Query("json", description="json or markdown"),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    repo = Repository(db)
    candidate = await repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate chain not found.")

    evidence_list = await repo.list_evidence_for_candidate(candidate_id)
    card = EvidenceCardBuilder.build_card(candidate, evidence_list)
    if format == "markdown":
        return {"markdown": EvidenceCardBuilder.to_markdown(card)}
    return card


@router.post("/{candidate_id}/transition")
async def transition_workflow_state(
    candidate_id: str,
    req: WorkflowTransitionRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)
    candidate = await repo.get_candidate(candidate_id)
    if not candidate or not candidate.score:
        raise HTTPException(status_code=404, detail="Candidate chain not found.")

    before_state = candidate.score.workflow_state
    candidate.score.workflow_state = req.workflow_state

    await repo.append_audit_log(
        actor=req.actor,
        action="workflow_state_transition",
        target_type="chain_product",
        target_id=candidate.id,
        before_state={"workflow_state": before_state},
        after_state={"workflow_state": req.workflow_state},
        reason=req.reason,
    )
    return {"success": True, "before": before_state, "current": req.workflow_state}


@router.post("/{candidate_id}/override_africa")
async def override_africa_assessment(
    candidate_id: str,
    req: AfricaOverrideRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)
    candidate = await repo.get_candidate(candidate_id)
    if not candidate or not candidate.assessment:
        raise HTTPException(status_code=404, detail="Candidate chain not found.")

    before = {
        "intent_label": candidate.assessment.intent_label,
        "total_score": candidate.assessment.total_score,
    }

    candidate.assessment.intent_label = req.intent_label
    if req.manual_score is not None:
        candidate.assessment.total_score = req.manual_score
    if req.countries:
        candidate.assessment.countries = req.countries

    candidate.assessment.analyst_override = {
        "actor": req.actor,
        "reason": req.reason,
        "overridden_at": str(datetime.now()),
    }

    # Rescore
    evs = await repo.list_evidence_for_candidate(candidate_id)
    res = scoring_engine.evaluate(
        chain=candidate,
        evidence_events=evs,
        africa_fit=candidate.assessment.total_score,
    )
    if candidate.score:
        candidate.score.outreach_score = res.outreach_score
        candidate.score.radar_score = res.radar_score
        candidate.score.state = res.state.value

    await repo.append_audit_log(
        actor=req.actor,
        action="africa_label_override",
        target_type="africa_assessment",
        target_id=candidate.assessment.id,
        before_state=before,
        after_state={"intent_label": req.intent_label, "score": candidate.assessment.total_score},
        reason=req.reason,
    )

    return {"success": True, "assessment": candidate.assessment.intent_label, "score": candidate.assessment.total_score}


@router.post("/{candidate_id}/verify")
async def verify_candidate_endpoints(
    candidate_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)
    candidate = await repo.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate chain not found.")

    results = []
    for net in candidate.networks:
        for rpc in net.rpc_urls:
            probe_res = await verifier_engine.probe_endpoint(rpc, family=candidate.stack_family)
            if probe_res.success:
                candidate.last_verified_at = probe_res.checked_at
            results.append({
                "endpoint": rpc,
                "success": probe_res.success,
                "identity": probe_res.identity.model_dump() if probe_res.identity else None,
                "head": probe_res.head.model_dump() if probe_res.head else None,
                "genesis": probe_res.genesis.model_dump() if probe_res.genesis else None,
                "error_type": probe_res.error_type,
                "error_detail": probe_res.error_detail,
            })

    return {"candidate_id": candidate_id, "probes": results}
