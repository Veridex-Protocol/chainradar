"""Intelligence digest generation and preview routes."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.alerting.digests import DigestGenerator
from src.storage.database import get_db_session

router = APIRouter(prefix="/digests", tags=["digests"])


@router.get("/preview")
async def preview_digest(
    type: str = Query("morning", description="morning (07:30 WAT) or evening (18:00 WAT)"),
    format: str = Query("json", description="json or markdown"),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    digest_data = await DigestGenerator.generate_digest(db, digest_type=type)
    if format == "markdown":
        return {"markdown": DigestGenerator.to_markdown(digest_data)}
    return digest_data
