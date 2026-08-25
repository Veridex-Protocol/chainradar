"""Activity and audience enrichment for confirmed candidates.

Discovery collectors answer "does this chain exist?". These probes answer the
questions an analyst asks next: *is anyone still working on it, does anyone
follow it, and is it worth an approach?*

Scope rules carried over from spec 23, because this is where they are easiest
to violate:

* Public, approved APIs only. Community member counts are read from a public
  widget endpoint or not at all - the engine never joins a Discord or Telegram
  to count members.
* A channel that could not be read is recorded as *not observed*, never as
  zero. Zero followers and "we could not check" mean very different things to
  someone deciding whether to reach out.
* All outbound traffic goes through the SSRF-hardened client, because a
  candidate's own metadata supplies these URLs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.storage.models import (
    ActivitySnapshot,
    ChainProduct,
    Network,
    Organization,
    VerificationObservation,
)
from src.util.redaction import redact_url
from src.util.timeutil import parse_iso, to_utc, utcnow
from src.verifier.safe_url import SafeHttpClient, SSRFValidationError

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class ProbeResult:
    """One channel's observation, or an explicit failure to observe it."""

    channel: str
    observed: bool
    channel_ref: Optional[str] = None
    last_activity_at: Optional[datetime] = None
    last_activity_kind: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    detail: Optional[str] = None


class GitHubActivityProbe:
    """Repository and organization activity - the clearest 'still building' signal.

    A chain whose repositories have not been pushed to in six months is not
    shipping, whatever its announcements say. Conversely a quiet Twitter with a
    busy monorepo is a heads-down team, which is a good time to approach.
    """

    channel = "github"

    def __init__(self, client: Optional[SafeHttpClient] = None) -> None:
        self.client = client or SafeHttpClient()

    @property
    def enabled(self) -> bool:
        # Unauthenticated GitHub is 60 requests/hour, which is not workable for
        # enrichment. Without a token this probe stays off rather than
        # burning the budget the discovery collectors need.
        return bool(settings.GITHUB_TOKEN)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
        return headers

    async def probe_org(self, org_login: str) -> ProbeResult:
        if not self.enabled:
            return ProbeResult(self.channel, observed=False, detail="GITHUB_TOKEN absent")
        try:
            response = await self.client.get(
                f"{GITHUB_API}/orgs/{org_login}", headers=self._headers()
            )
            if response.status_code != 200:
                return ProbeResult(
                    self.channel, observed=False, detail=f"HTTP {response.status_code}"
                )
            data = response.json()
        except (SSRFValidationError, Exception) as exc:
            return ProbeResult(self.channel, observed=False, detail=str(exc)[:200])

        return ProbeResult(
            channel=self.channel,
            observed=True,
            channel_ref=f"github.com/{org_login}",
            last_activity_at=parse_iso(data.get("updated_at")),
            last_activity_kind="org_profile_update",
            metrics={
                "followers": data.get("followers"),
                "public_repos": data.get("public_repos"),
                "org_created_at": data.get("created_at"),
            },
        )

    async def probe_repo(self, owner: str, repo: str) -> ProbeResult:
        """Repository health: last push, throughput, audience."""
        if not self.enabled:
            return ProbeResult(self.channel, observed=False, detail="GITHUB_TOKEN absent")

        try:
            response = await self.client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}", headers=self._headers()
            )
            if response.status_code != 200:
                return ProbeResult(
                    self.channel, observed=False, detail=f"HTTP {response.status_code}"
                )
            data = response.json()
        except Exception as exc:
            return ProbeResult(self.channel, observed=False, detail=str(exc)[:200])

        pushed_at = parse_iso(data.get("pushed_at"))
        metrics: Dict[str, Any] = {
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "watchers": data.get("subscribers_count"),
            "archived": data.get("archived"),
            "default_branch": data.get("default_branch"),
        }

        # An archived repository is a definitive statement by the owner that
        # work has stopped; worth surfacing distinctly from mere silence.
        if data.get("archived"):
            metrics["archived"] = True

        since = (utcnow() - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        try:
            commits = await self.client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/commits?since={since}&per_page=100",
                headers=self._headers(),
            )
            if commits.status_code == 200:
                payload = commits.json()
                metrics["commits_last_30d"] = len(payload) if isinstance(payload, list) else None
        except Exception as exc:
            logger.debug("Commit probe failed for %s/%s: %s", owner, repo, exc)

        try:
            releases = await self.client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/releases?per_page=20",
                headers=self._headers(),
            )
            if releases.status_code == 200:
                payload = releases.json()
                if isinstance(payload, list):
                    cutoff = utcnow() - timedelta(days=90)
                    recent = [
                        r for r in payload
                        if (parse_iso(r.get("published_at")) or utcnow() - timedelta(days=3650)) >= cutoff
                    ]
                    metrics["releases_last_90d"] = len(recent)
                    if payload:
                        latest = parse_iso(payload[0].get("published_at"))
                        if latest and (pushed_at is None or latest > pushed_at):
                            pushed_at = latest
        except Exception as exc:
            logger.debug("Release probe failed for %s/%s: %s", owner, repo, exc)

        return ProbeResult(
            channel=self.channel,
            observed=True,
            channel_ref=f"github.com/{owner}/{repo}",
            last_activity_at=pushed_at,
            last_activity_kind="push_or_release",
            metrics=metrics,
        )


class WebActivityProbe:
    """Last publication on the project's own site.

    An official site that has not published in months, from a project claiming
    an imminent mainnet, is a meaningful contradiction.
    """

    channel = "blog"

    def __init__(self, client: Optional[SafeHttpClient] = None) -> None:
        self.client = client or SafeHttpClient()

    async def probe(self, domain: str) -> ProbeResult:
        import feedparser

        for path in ("/feed", "/rss.xml", "/blog/rss.xml", "/feed.xml", "/atom.xml"):
            url = f"https://{domain.rstrip('/')}{path}"
            try:
                response = await self.client.get(url)
            except Exception:
                continue
            if response.status_code != 200 or not response.content:
                continue

            parsed = feedparser.parse(response.content)
            if not parsed.entries:
                continue

            dates = [
                parse_iso(entry.get("published") or entry.get("updated"))
                for entry in parsed.entries
            ]
            dates = [d for d in dates if d]
            if not dates:
                continue

            cutoff = utcnow() - timedelta(days=30)
            return ProbeResult(
                channel=self.channel,
                observed=True,
                channel_ref=redact_url(url),
                last_activity_at=max(dates),
                last_activity_kind="post_published",
                metrics={
                    "posts_last_30d": sum(1 for d in dates if d >= cutoff),
                    "entries_seen": len(parsed.entries),
                },
            )

        return ProbeResult(self.channel, observed=False, detail="no readable public feed")


class SocialActivityProbe:
    """Public social reach, via approved APIs only.

    Every provider here needs a credential and is disabled without one. There
    is deliberately no scraping fallback: an unavailable channel is reported as
    unobserved, which is the honest answer.
    """

    def __init__(self, client: Optional[SafeHttpClient] = None) -> None:
        self.client = client or SafeHttpClient()

    def available_channels(self) -> List[str]:
        channels = []
        if settings.X_API_TOKEN:
            channels.append("x")
        if settings.NEYNAR_API_KEY:
            channels.append("farcaster")
        return channels

    async def probe(self, channel: str, handle: str) -> ProbeResult:
        if channel == "x" and settings.X_API_TOKEN:
            return await self._probe_x(handle)
        if channel == "farcaster" and settings.NEYNAR_API_KEY:
            return await self._probe_farcaster(handle)
        return ProbeResult(
            channel, observed=False, detail=f"no approved API credential for {channel}"
        )

    async def _probe_x(self, handle: str) -> ProbeResult:
        url = (
            f"https://api.x.com/2/users/by/username/{handle.lstrip('@')}"
            "?user.fields=public_metrics,created_at"
        )
        try:
            response = await self.client.get(
                url, headers={"Authorization": f"Bearer {settings.X_API_TOKEN}"}
            )
            if response.status_code != 200:
                return ProbeResult("x", observed=False, detail=f"HTTP {response.status_code}")
            data = (response.json() or {}).get("data") or {}
        except Exception as exc:
            return ProbeResult("x", observed=False, detail=str(exc)[:200])

        metrics = data.get("public_metrics") or {}
        return ProbeResult(
            channel="x",
            observed=True,
            channel_ref=f"x.com/{handle.lstrip('@')}",
            # The profile endpoint gives reach, not recency; last-post time
            # needs the timeline endpoint and its own API entitlement.
            last_activity_at=None,
            last_activity_kind=None,
            metrics={
                "followers": metrics.get("followers_count"),
                "following": metrics.get("following_count"),
                "posts": metrics.get("tweet_count"),
            },
        )

    async def _probe_farcaster(self, handle: str) -> ProbeResult:
        url = f"https://api.neynar.com/v2/farcaster/user/by_username?username={handle.lstrip('@')}"
        try:
            response = await self.client.get(
                url, headers={"api_key": settings.NEYNAR_API_KEY, "x-api-key": settings.NEYNAR_API_KEY}
            )
            if response.status_code != 200:
                return ProbeResult("farcaster", observed=False, detail=f"HTTP {response.status_code}")
            user = (response.json() or {}).get("user") or {}
        except Exception as exc:
            return ProbeResult("farcaster", observed=False, detail=str(exc)[:200])

        return ProbeResult(
            channel="farcaster",
            observed=True,
            channel_ref=f"farcaster/{handle.lstrip('@')}",
            metrics={
                "followers": user.get("follower_count"),
                "following": user.get("following_count"),
            },
        )


class ActivityEnricher:
    """Refreshes the activity picture for one candidate."""

    def __init__(self, session: AsyncSession, client: Optional[SafeHttpClient] = None) -> None:
        self.session = session
        client = client or SafeHttpClient()
        self.github = GitHubActivityProbe(client)
        self.web = WebActivityProbe(client)
        self.social = SocialActivityProbe(client)

    async def refresh(self, candidate: ChainProduct) -> List[ActivitySnapshot]:
        """Probe every channel we know about and persist what we observed."""
        results: List[ProbeResult] = []
        org: Optional[Organization] = candidate.organization

        if org:
            for login in list(org.github_orgs or [])[:2]:
                results.append(await self.github.probe_org(login))
            for domain in list(org.official_domains or [])[:2]:
                results.append(await self.web.probe(domain))
            for platform, handle in (org.social_handles or {}).items():
                if platform in ("x", "twitter"):
                    results.append(await self.social.probe("x", handle))
                elif platform == "farcaster":
                    results.append(await self.social.probe("farcaster", handle))

        results.append(await self._chain_activity(candidate))

        snapshots: List[ActivitySnapshot] = []
        for result in results:
            if not result.observed:
                # Not recorded: an unread channel must not masquerade as a
                # silent one when vitality is assessed.
                logger.debug(
                    "Channel %s not observed for %s: %s",
                    result.channel, candidate.id, result.detail,
                )
                continue
            snapshots.append(self._persist(candidate, result))

        await self.session.flush()
        return snapshots

    async def _chain_activity(self, candidate: ChainProduct) -> ProbeResult:
        """Chain-side liveness from the stored verification observations."""
        stmt = (
            select(VerificationObservation)
            .where(
                VerificationObservation.candidate_id == candidate.id,
                VerificationObservation.success.is_(True),
            )
            .order_by(VerificationObservation.observed_at.desc())
            .limit(1)
        )
        observation = (await self.session.execute(stmt)).scalars().first()
        if observation is None:
            return ProbeResult("rpc", observed=False, detail="no successful probe recorded")

        return ProbeResult(
            channel="rpc",
            observed=True,
            channel_ref=observation.endpoint,
            last_activity_at=to_utc(observation.observed_at),
            last_activity_kind="block_observed",
            metrics={
                "block_height": observation.block_height,
                "chain_id": observation.chain_id,
                "client_version": observation.client_version,
            },
        )

    def _persist(self, candidate: ChainProduct, result: ProbeResult) -> ActivitySnapshot:
        metrics = result.metrics or {}
        snapshot = ActivitySnapshot(
            candidate_id=candidate.id,
            org_id=candidate.organization_id,
            channel=result.channel,
            channel_ref=result.channel_ref,
            last_activity_at=result.last_activity_at,
            last_activity_kind=result.last_activity_kind,
            followers=metrics.get("followers"),
            stars=metrics.get("stars"),
            forks=metrics.get("forks"),
            contributors=metrics.get("contributors"),
            commits_last_30d=metrics.get("commits_last_30d"),
            releases_last_90d=metrics.get("releases_last_90d"),
            posts_last_30d=metrics.get("posts_last_30d"),
            open_issues=metrics.get("open_issues"),
            block_height=metrics.get("block_height"),
            extra_metrics={
                k: v
                for k, v in metrics.items()
                if k not in {
                    "followers", "stars", "forks", "contributors", "commits_last_30d",
                    "releases_last_90d", "posts_last_30d", "open_issues", "block_height",
                }
            },
        )
        self.session.add(snapshot)
        return snapshot

    async def latest_snapshots(self, candidate_id: str) -> List[ActivitySnapshot]:
        """Most recent snapshot per channel for a candidate."""
        stmt = (
            select(ActivitySnapshot)
            .where(ActivitySnapshot.candidate_id == candidate_id)
            .order_by(ActivitySnapshot.observed_at.desc())
            .limit(200)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        newest: Dict[str, ActivitySnapshot] = {}
        for row in rows:
            if row.channel not in newest:
                newest[row.channel] = row
        return list(newest.values())
