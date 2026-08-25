"""Privacy compliance, NDPA GAID 2025 / GDPR data subject handling, and suppression controls."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from src.config import settings
from src.storage.models import Contact
from src.storage.repository import Repository


class PrivacyComplianceManager:
    """Enforces lawful basis, data minimization, 90-day contact retention, and suppression."""

    @staticmethod
    async def suppress_contact(
        session: AsyncSession,
        channel_value: str,
        reason: str = "Data subject opt-out request",
        actor: str = "compliance_officer",
    ) -> None:
        """Suppresses a contact across all entities and retains only the SHA-256 hash."""
        repo = Repository(session)
        await repo.add_suppression(channel_value, reason=reason, actor=actor)

    @staticmethod
    async def run_90_day_contact_retention_cleanup(session: AsyncSession) -> int:
        """Deletes unverified/inactive personal business contacts older than 90 days, retaining suppression hashes."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.CONTACT_INACTIVITY_DAYS)
        
        # Select active (non-suppressed) contacts older than cutoff
        stmt = (
            delete(Contact)
            .where(
                Contact.last_verified_at < cutoff,
                Contact.suppressed == False,
            )
        )
        result = await session.execute(stmt)
        deleted_count = result.rowcount or 0
        return deleted_count

    @staticmethod
    def hash_identifier(identifier: str) -> str:
        norm = identifier.lower().strip()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()
