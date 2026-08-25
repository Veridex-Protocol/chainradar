"""Intelligence report generator writing digests, evidence cards, and candidate datasets to disk."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.alerting.digests import DigestGenerator
from src.alerting.evidence_card import EvidenceCardBuilder
from src.storage.database import db_manager
from src.storage.models import ChainProduct
from src.storage.repository import Repository


class ReportGenerator:
    """Generates scheduled and on-demand intelligence reports on disk."""

    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = Path(output_dir).resolve()
        self.digests_dir = self.output_dir / "digests"
        self.alerts_dir = self.output_dir / "alerts"
        self.exports_dir = self.output_dir / "exports"

        self.digests_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    async def generate_digest(
        self, session: AsyncSession, digest_type: str = "morning", save_to_disk: bool = True
    ) -> Dict[str, Any]:
        """Generates 07:30 WAT morning or 18:00 WAT evening digest."""
        digest_data = await DigestGenerator.generate_digest(session, digest_type=digest_type)
        
        if save_to_disk:
            now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"digest_{digest_type}_{now_str}"
            
            # Save Markdown
            md_path = self.digests_dir / f"{filename}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(digest_data["markdown"])

            # Save JSON
            json_path = self.digests_dir / f"{filename}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(digest_data["payload"], f, indent=2, default=str)

            digest_data["saved_files"] = {
                "markdown": str(md_path),
                "json": str(json_path),
            }

        return digest_data

    async def export_candidates_csv(self, session: AsyncSession) -> str:
        """Exports all active discovery candidates to a CSV spreadsheet report."""
        repo = Repository(session)
        candidates = await repo.list_candidates(limit=500)
        
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_path = self.exports_dir / f"candidates_export_{now_str}.csv"

        fieldnames = [
            "id",
            "name",
            "slug",
            "organization",
            "stage",
            "stack_family",
            "layer",
            "africa_intent",
            "africa_score",
            "outreach_score",
            "radar_score",
            "confidence",
            "risk",
            "state",
            "workflow_state",
            "first_seen_at",
            "last_verified_at",
        ]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for c in candidates:
                org_name = c.organization.display_name if c.organization else "Unattributed"
                a_label = c.assessment.intent_label if c.assessment else "A4_no_evidence"
                a_score = c.assessment.total_score if c.assessment else 0.0
                outreach_s = c.score.outreach_score if c.score else 0.0
                radar_s = c.score.radar_score if c.score else 0.0
                conf_s = c.score.confidence if c.score else 0.0
                risk_s = c.score.risk if c.score else 0.0
                state_s = c.score.state if c.score else "RADAR"
                wf_s = c.score.workflow_state if c.score else "NEW"

                writer.writerow({
                    "id": c.id,
                    "name": c.canonical_name,
                    "slug": c.slug,
                    "organization": org_name,
                    "stage": c.stage,
                    "stack_family": c.stack_family,
                    "layer": c.layer or "L2",
                    "africa_intent": a_label,
                    "africa_score": a_score,
                    "outreach_score": outreach_s,
                    "radar_score": radar_s,
                    "confidence": conf_s,
                    "risk": risk_s,
                    "state": state_s,
                    "workflow_state": wf_s,
                    "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else "",
                    "last_verified_at": c.last_verified_at.isoformat() if c.last_verified_at else "",
                })

        return str(csv_path)

    async def save_evidence_card(self, candidate: ChainProduct, evidence_events: list) -> str:
        """Saves a standalone markdown Evidence Card for an analyst brief."""
        card_md = EvidenceCardBuilder.build_markdown_card(candidate, evidence_events)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug = candidate.slug or "candidate"
        path = self.alerts_dir / f"card_{slug}_{now_str}.md"

        with open(path, "w", encoding="utf-8") as f:
            f.write(card_md)

        return str(path)


report_generator = ReportGenerator()
