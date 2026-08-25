"""Morning (07:30 WAT) and Evening (18:00 WAT) intelligence digest generators."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from sqlalchemy.ext.asyncio import AsyncSession
from src.alerting.evidence_card import EvidenceCardBuilder
from src.storage.models import ChainProduct
from src.storage.repository import Repository


class DigestGenerator:
    """Builds structured morning and evening competitive intelligence digests."""

    @staticmethod
    async def generate_digest(
        session: AsyncSession,
        digest_type: str = "morning", # "morning" (07:30 WAT) or "evening" (18:00 WAT)
    ) -> Dict[str, Any]:
        repo = Repository(session)
        
        hot_candidates = await repo.list_candidates(state="HOT", limit=20)
        qualified_candidates = await repo.list_candidates(state="QUALIFIED", limit=30)
        radar_candidates = await repo.list_candidates(state="RADAR", limit=20)

        now = datetime.now(timezone.utc)
        title = f"Ashinity Early Chain Digest - {digest_type.upper()} ({now.strftime('%Y-%m-%d %H:%M UTC')})"

        hot_cards = []
        for c in hot_candidates:
            evs = await repo.list_evidence_for_candidate(c.id)
            hot_cards.append(EvidenceCardBuilder.build_card(c, evs))

        qual_cards = []
        for c in qualified_candidates:
            evs = await repo.list_evidence_for_candidate(c.id)
            qual_cards.append(EvidenceCardBuilder.build_card(c, evs))

        return {
            "title": title,
            "digest_type": digest_type,
            "generated_at": now.isoformat(),
            "summary": {
                "hot_count": len(hot_candidates),
                "qualified_count": len(qualified_candidates),
                "radar_count": len(radar_candidates),
            },
            "hot_candidates": hot_cards,
            "qualified_candidates": qual_cards,
        }

    @staticmethod
    def to_markdown(digest_data: Dict[str, Any]) -> str:
        s = digest_data["summary"]
        md = f"""# {digest_data['title']}

**Summary**: 
- 🔥 **HOT Immediate Alerts**: `{s['hot_count']}`
- 🎯 **QUALIFIED Leads**: `{s['qualified_count']}`
- 📡 **Active Radar Watch**: `{s['radar_count']}`

---

## 🔥 Top HOT Alerts (Immediate Action Required)
"""
        if not digest_data["hot_candidates"]:
            md += "_No new HOT alerts in this window._\n\n"
        for card in digest_data["hot_candidates"]:
            h = card["header"]
            a = card["africa"]
            sc = card["scores"]
            md += f"### [{h['canonical_name']}](#) ({h['stage']})\n"
            md += f"- **Org / Family**: {h['organization']} | {h['family']}\n"
            md += f"- **Africa**: **{a['label']}** ({a['score']}/100) - {', '.join(a['countries']) if a['countries'] else 'Region'}\n"
            md += f"- **Outreach Priority**: **{sc['outreach_score']}/100** (Confidence: {sc['confidence']})\n"
            md += f"- **Action**: {card['recommendation']}\n\n"

        md += "\n## 🎯 Newly QUALIFIED Candidates\n"
        if not digest_data["qualified_candidates"]:
            md += "_No newly qualified leads in this window._\n\n"
        for card in digest_data["qualified_candidates"][:10]:
            h = card["header"]
            a = card["africa"]
            sc = card["scores"]
            md += f"- **{h['canonical_name']}** ({h['family']}, {h['stage']}): Outreach {sc['outreach_score']} | Africa {a['label']} ({a['score']}) -> *{card['recommendation']}*\n"

        return md
