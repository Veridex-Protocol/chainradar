"""Raw evidence drill-down and payload retrieval routes."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.storage.database import get_db_session
from src.storage.object_store import object_store
from src.storage.repository import Repository

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{evidence_id}")
async def get_evidence_detail(
    evidence_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    repo = Repository(db)
    ev = await repo.get_evidence(evidence_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence record not found.")

    raw_payload = None
    if ev.raw_payload_path:
        raw_payload = object_store.retrieve_payload(ev.raw_payload_path)

    return {
        "id": ev.id,
        "source_id": ev.source_id,
        "external_id": ev.external_id,
        "url": ev.url,
        "source_family": ev.source_family,
        "observed_at": ev.observed_at.isoformat(),
        "published_at": ev.published_at.isoformat() if ev.published_at else None,
        "content_hash": ev.content_hash,
        "raw_payload_path": ev.raw_payload_path,
        "extracted_claims": ev.extracted_claims,
        "reliability": ev.reliability,
        "parser_version": ev.parser_version,
        "raw_payload": raw_payload,
    }
