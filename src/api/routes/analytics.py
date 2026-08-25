"""Analytics, funnel progression, and Africa Matrix routes."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import lexicons
from src.storage.database import get_db_session
from src.storage.models import AfricaAssessment, ChainProduct, ScoreSnapshot

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/funnel")
async def get_funnel_metrics(db: AsyncSession = Depends(get_db_session)) -> Dict[str, Any]:
    # Count by State
    state_stmt = select(ScoreSnapshot.state, func.count(ScoreSnapshot.id)).group_by(ScoreSnapshot.state)
    state_res = await db.execute(state_stmt)
    state_counts = dict(state_res.all())

    # Count by Workflow State
    wf_stmt = select(ScoreSnapshot.workflow_state, func.count(ScoreSnapshot.id)).group_by(ScoreSnapshot.workflow_state)
    wf_res = await db.execute(wf_stmt)
    wf_counts = dict(wf_res.all())

    # Count by Africa Label
    a_stmt = select(AfricaAssessment.intent_label, func.count(AfricaAssessment.id)).group_by(AfricaAssessment.intent_label)
    a_res = await db.execute(a_stmt)
    a_counts = dict(a_res.all())

    # Count by Stack Family
    stack_stmt = select(ChainProduct.stack_family, func.count(ChainProduct.id)).group_by(ChainProduct.stack_family)
    stack_res = await db.execute(stack_stmt)
    stack_counts = dict(stack_res.all())

    return {
        "pipeline_state": state_counts,
        "workflow_state": wf_counts,
        "africa_labels": a_counts,
        "stack_families": stack_counts,
    }


@router.get("/africa_matrix")
async def get_africa_matrix(db: AsyncSession = Depends(get_db_session)) -> Dict[str, Any]:
    stmt = select(AfricaAssessment)
    res = await db.execute(stmt)
    assessments = res.scalars().all()

    country_counts: Dict[str, int] = {}
    region_counts: Dict[str, int] = {}

    for a in assessments:
        for c in a.countries:
            country_counts[c] = country_counts.get(c, 0) + 1
        for r in a.regions:
            region_counts[r] = region_counts.get(r, 0) + 1

    # Top priority markets
    priority_breakdown = []
    for iso in ["NG", "KE", "GH", "ZA", "RW", "EG", "MA", "UG", "TZ", "SN", "CI"]:
        c_obj = lexicons.country_by_iso2.get(iso)
        c_name = c_obj["name"] if c_obj else iso
        count = country_counts.get(c_name, 0)
        priority_breakdown.append({
            "iso2": iso,
            "country": c_name,
            "chain_count": count,
        })

    return {
        "priority_markets": priority_breakdown,
        "country_counts": country_counts,
        "region_counts": region_counts,
    }
