"""Source register and collector management routes."""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.collectors.ats.job_boards import ATSJobBoardsCollector
from src.collectors.github.hyper_search import GitHubHyperSearchCollector
from src.collectors.registries.chainid_network import ChainIdNetworkCollector
from src.collectors.registries.cosmos_registry import CosmosRegistryCollector
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.collectors.registries.superchain import SuperchainCollector
from src.collectors.web_news.rss_sitemaps import RSSFeedsCollector
from src.config import source_register
from src.core.pipeline import IntelligencePipeline
from src.storage.database import get_db_session
from src.storage.repository import Repository

router = APIRouter(prefix="/sources", tags=["sources"])


class KillSwitchRequest(BaseModel):
    disabled: bool
    reason: str
    actor: str = "operator"


@router.get("")
async def list_sources(db: AsyncSession = Depends(get_db_session)) -> Dict[str, Any]:
    repo = Repository(db)
    items = []
    for s_id, s_cfg in source_register.sources.items():
        cur = await repo.get_cursor(s_id)
        items.append({
            "source_id": s_id,
            "name": s_cfg.name,
            "family": s_cfg.family,
            "tier": s_cfg.tier,
            "owner": s_cfg.owner,
            "terms_url": s_cfg.terms_url,
            "reliability": s_cfg.reliability,
            "cadence": s_cfg.cadence,
            "kill_switch": s_cfg.kill_switch,
            "last_success": cur.last_success.isoformat() if cur and cur.last_success else None,
            "consecutive_failures": cur.consecutive_failures if cur else 0,
            "etag": cur.etag if cur else None,
        })
    return {"total": len(items), "sources": items}


@router.post("/{source_id}/toggle_kill_switch")
async def toggle_kill_switch(
    source_id: str,
    req: KillSwitchRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    if source_id not in source_register.sources:
        raise HTTPException(status_code=404, detail="Source not found.")

    source_register.set_kill_switch(source_id, req.disabled)
    repo = Repository(db)
    await repo.append_audit_log(
        actor=req.actor,
        action="source_kill_switch_toggled",
        target_type="source",
        target_id=source_id,
        after_state={"kill_switch": req.disabled, "reason": req.reason},
        reason=req.reason,
    )
    return {"source_id": source_id, "disabled": req.disabled}


@router.post("/{source_id}/trigger_sync")
async def trigger_sync(
    source_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    if not source_register.is_enabled(source_id):
        raise HTTPException(status_code=400, detail="Source is currently disabled by kill switch.")

    pipeline = IntelligencePipeline(db)
    count = 0

    if source_id == "ethereum_lists":
        count = await pipeline.run_collector_batch(EthereumListsCollector())
    elif source_id == "chainid_network":
        count = await pipeline.run_collector_batch(ChainIdNetworkCollector())
    elif source_id == "superchain_registry":
        count = await pipeline.run_collector_batch(SuperchainCollector())
    elif source_id == "cosmos_chain_registry":
        count = await pipeline.run_collector_batch(CosmosRegistryCollector())
    elif source_id == "github_hyper_search":
        count = await pipeline.run_collector_batch(GitHubHyperSearchCollector())
    elif source_id == "rss_sitemaps":
        count = await pipeline.run_collector_batch(RSSFeedsCollector())
    elif source_id == "ats_job_boards":
        count = await pipeline.run_collector_batch(ATSJobBoardsCollector())
    else:
        raise HTTPException(status_code=400, detail=f"No manual sync handler for source '{source_id}'")

    return {"source_id": source_id, "processed_items": count}
