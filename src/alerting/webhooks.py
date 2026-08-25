"""Webhook dispatcher for Slack, Discord, and HTTP receivers."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import httpx
from src.config import settings
from src.verifier.safe_url import safe_http_client

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    """Dispatches HOT candidate alerts and daily digests to configured endpoints."""

    @staticmethod
    async def dispatch_hot_alert(card: Dict[str, Any]) -> bool:
        """Sends an immediate HOT alert to configured webhook URLs."""
        h = card["header"]
        a = card["africa"]
        s = card["scores"]

        payload = {
            "event": "candidate_hot_alert",
            "candidate_id": h["candidate_id"],
            "name": h["canonical_name"],
            "organization": h["organization"],
            "stage": h["stage"],
            "family": h["family"],
            "africa_label": a["label"],
            "africa_score": a["score"],
            "countries": a["countries"],
            "outreach_score": s["outreach_score"],
            "confidence": s["confidence"],
            "recommendation": card["recommendation"],
            "evidence_count": card["why_now"]["recent_signals_count"],
        }

        success = True
        urls = [u for u in [settings.ALERT_WEBHOOK_URL, settings.DISCORD_WEBHOOK_URL, settings.SLACK_WEBHOOK_URL] if u]
        
        for url in urls:
            try:
                # Format for Discord/Slack if needed
                formatted_body = payload
                if "discord.com" in url:
                    formatted_body = {
                        "content": f"🔥 **HOT Blockchain Discovery**: **{h['canonical_name']}** ({h['stage']})\n"
                                   f"• **Africa**: `{a['label']}` ({a['score']}/100) -> {', '.join(a['countries']) or 'Region'}\n"
                                   f"• **Outreach Priority**: `{s['outreach_score']}/100` | Confidence: `{s['confidence']}`\n"
                                   f"• **Next Action**: {card['recommendation']}"
                    }
                elif "slack.com" in url:
                    formatted_body = {
                        "text": f"🔥 *HOT Blockchain Discovery*: *{h['canonical_name']}* ({h['stage']})\n"
                                f"• *Africa*: `{a['label']}` ({a['score']}/100) -> {', '.join(a['countries']) or 'Region'}\n"
                                f"• *Outreach Priority*: `{s['outreach_score']}/100`\n"
                                f"• *Action*: {card['recommendation']}"
                    }

                resp = await safe_http_client.post_json(url, formatted_body)
                if resp.status_code >= 400:
                    logger.warning(f"Webhook dispatch returned {resp.status_code} for {url}")
                    success = False
            except Exception as e:
                logger.error(f"Failed to dispatch webhook to {url}: {e}")
                success = False

        return success


webhook_dispatcher = WebhookDispatcher()
