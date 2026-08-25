"""ATS and Public Career Job Board collectors (Greenhouse, Lever, Ashby)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.collectors.base import TokenBucketLimiter
from src.config import lexicons
from src.core.normalizer import extract_effective_domain
from src.core.types import (
    Cursor,
    FetchBatch,
    LifecycleStage,
    NetworkEnvironment,
    RateBudget,
    RawItem,
    RawObservation,
    StackFamily,
)
from src.verifier.safe_url import safe_http_client


JOB_ROLE_PATTERN = re.compile(
    r"\b(community|developer relations|devrel|ecosystem|growth|partnerships|business development|bd|country manager|regional lead|government relations|developer advocate|ambassador)\b",
    re.IGNORECASE,
)


class ATSJobBoardsCollector:
    source_id: str = "ats_job_boards"
    family: str = "careers"

    def __init__(self, monitored_slugs: Optional[List[Dict[str, str]]] = None):
        self.limiter = TokenBucketLimiter(requests_per_minute=30, burst=5)
        # Monitored ATS slugs: [{"platform": "greenhouse", "slug": "optimism", "org_name": "Optimism Foundation"}]
        self.monitored_slugs = monitored_slugs or []

    def add_slug(self, platform: str, slug: str, org_name: str) -> None:
        self.monitored_slugs.append({"platform": platform.lower(), "slug": slug, "org_name": org_name})

    async def fetch(self, cursor: Cursor, budget: RateBudget) -> FetchBatch:
        items: List[RawItem] = []
        now = datetime.now(timezone.utc)

        for target in self.monitored_slugs:
            if not await self.limiter.acquire(1):
                break
            platform = target["platform"]
            slug = target["slug"]
            org_name = target["org_name"]

            url = ""
            if platform == "greenhouse":
                url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            elif platform == "lever":
                url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            elif platform == "ashby":
                url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"

            if not url:
                continue

            try:
                resp = await safe_http_client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    jobs = data.get("jobs", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for job in jobs[:15]:
                        title = job.get("title") or job.get("text", "")
                        location = ""
                        if isinstance(job.get("location"), dict):
                            location = job.get("location", {}).get("name", "")
                        elif isinstance(job.get("categories"), dict):
                            location = job.get("categories", {}).get("location", "")
                        elif isinstance(job.get("location"), str):
                            location = job.get("location", "")

                        absolute_url = job.get("absolute_url") or job.get("hostedUrl") or job.get("jobUrl", "")
                        
                        payload = {
                            "platform": platform,
                            "slug": slug,
                            "org_name": org_name,
                            "title": title,
                            "location": location,
                            "url": absolute_url,
                            "raw_job": job,
                        }
                        c_str = json.dumps(payload, sort_keys=True)
                        c_hash = hashlib.sha256(c_str.encode("utf-8")).hexdigest()

                        items.append(
                            RawItem(
                                source_id=self.source_id,
                                external_id=f"ats_{platform}_{slug}_{c_hash[:16]}",
                                url=absolute_url or url,
                                source_family=self.family,
                                observed_at=now,
                                raw_payload=payload,
                                content_hash=c_hash,
                                provenance={"platform": platform, "slug": slug, "org": org_name},
                            )
                        )
            except Exception:
                pass

        return FetchBatch(
            source_id=self.source_id,
            items=items,
            next_cursor=Cursor(source_id=self.source_id, last_seen_timestamp=now),
            provenance={"count": len(items)},
        )

    def normalize(self, raw: RawItem) -> List[RawObservation]:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        org_name = payload.get("org_name", "Unknown Organization")
        title = payload.get("title", "")
        location = payload.get("location", "")
        job_url = payload.get("url", "")
        combined_text = f"{title} {location}"

        # Check job role match
        has_role_match = bool(JOB_ROLE_PATTERN.search(title))
        
        # Check African Geography
        matched_geo = []
        for c in lexicons.countries:
            c_name = c["name"].lower()
            if c_name in combined_text.lower() or c["iso2"].lower() in location.lower().split():
                matched_geo.append(c["name"])
            for alias in c.get("aliases", []):
                if alias.lower() in combined_text.lower():
                    matched_geo.append(c["name"])

        for hub in lexicons.priority_hubs:
            if hub["city"].lower() in combined_text.lower():
                matched_geo.append(hub["city"])

        # Determine Signal Strength
        signal_strength = 0.2
        if has_role_match and matched_geo:
            signal_strength = 1.0
        elif ("emea" in combined_text.lower() or "africa" in combined_text.lower()) and has_role_match:
            signal_strength = 0.6

        opp = {
            "opportunity_type": "market_entry_bd" if "bd" in title.lower() or "manager" in title.lower() else "developer_relations",
            "geography": ", ".join(matched_geo) if matched_geo else location,
            "summary": f"Active hiring for {title} (Location: {location})",
            "url": job_url,
            "signal_strength": signal_strength,
        }

        contact = {
            "role_type": "recruiting",
            "channel_type": "application_url",
            "channel_value": job_url,
            "permitted_purpose": "careers_and_partnership",
            "source_url": job_url or raw.url,
        }

        obs = RawObservation(
            candidate_name=org_name,
            organization_name=org_name,
            stack_family=StackFamily.EVM,
            environment=NetworkEnvironment.TESTNET,
            is_public=True,
            stage=LifecycleStage.S1_DEVNET_PROTOTYPE,
            raw_text=combined_text,
            claims={"job_title": title, "job_location": location, "signal_strength": signal_strength, "matched_geo": matched_geo},
            opportunities=[opp],
            contacts=[contact] if job_url else [],
            reliability=0.80,
        )
        return [obs]

    def next_cursor(self, batch: FetchBatch) -> Cursor:
        return batch.next_cursor
