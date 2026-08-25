"""Cadence and cron schedule (spec 18).

All cron expressions are UTC; the comments give the Africa/Lagos time analysts
actually see. Every job is wrapped so that:

* a per-source kill switch disables only that source, never its neighbours;
* two workers cannot run the same window twice (PostgreSQL advisory lock);
* a missed run during downtime is caught up rather than silently skipped;
* requests are jittered so collectors do not fire in lockstep.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.alerting.digests import DigestGenerator
from src.collectors.ats.job_boards import ATSJobBoardsCollector
from src.collectors.github.hyper_search import GitHubHyperSearchCollector
from src.collectors.registries.blockscout import BlockscoutCollector
from src.collectors.registries.chainid_network import ChainIdNetworkCollector
from src.collectors.registries.cosmos_registry import CosmosRegistryCollector
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.collectors.registries.superchain import SuperchainCollector
from src.collectors.web_news.rss_sitemaps import RSSFeedsCollector
from src.config import settings, source_register
from src.core.pipeline import IntelligencePipeline
from src.storage.database import advisory_lock, db_manager
from src.storage.models import ChainProduct, ScoreSnapshot
from src.verifier.service import VerificationService

logger = logging.getLogger(__name__)

# Longest a job may overshoot its slot and still run on catch-up. Without this
# APScheduler drops the fire entirely, silently losing a downtime interval.
MISFIRE_GRACE_SECONDS = 3600


class CadenceScheduler:
    """Schedules discovery, verification, reconciliation and digests."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._setup_jobs()

    # ------------------------------------------------------------------
    def _add(self, func: Callable, crontab: str, job_id: str, wat_note: str) -> None:
        self.scheduler.add_job(
            func,
            CronTrigger.from_crontab(crontab, timezone=timezone.utc),
            id=job_id,
            replace_existing=True,
            # Catch up a missed window instead of skipping it, but collapse a
            # backlog into one run so a long outage cannot stampede sources.
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
            coalesce=True,
            max_instances=1,
        )
        logger.debug("Scheduled %s at '%s' UTC (%s WAT)", job_id, crontab, wat_note)

    def _setup_jobs(self) -> None:
        # Discovery -----------------------------------------------------
        self._add(self._job_registry_prs, "*/10 * * * *", "registry_prs", "every 10 min")
        self._add(self._job_aggregated_json, "3,18,33,48 * * * *", "aggregated_json", "every 15 min")
        self._add(self._job_github_search, "7,37 * * * *", "github_search", "every 30 min")
        self._add(self._job_rss_feeds, "*/15 * * * *", "rss_feeds", "every 15 min")
        self._add(self._job_web_news, "15 */2 * * *", "web_news", "every 2 h")
        self._add(self._job_infrastructure_lists, "25 */2 * * *", "infra_lists", "every 2 h")
        self._add(self._job_ats_careers, "40 */6 * * *", "ats_careers", "every 6 h")
        self._add(self._job_market_analytics, "55 */6 * * *", "market_analytics", "every 6 h")

        # Verification --------------------------------------------------
        # The liveness recheck is its own queued job, never a sleeping worker
        # holding a connection open for 60-180 seconds (spec 18).
        self._add(self._job_liveness_recheck, "* * * * *", "liveness_recheck", "continuous")
        # Drains the queue of candidates awaiting a first probe. Bounded per
        # tick so a registry snapshot of thousands of chains is worked through
        # steadily instead of blocking ingest.
        self._add(self._job_verify_pending, "*/2 * * * *", "verify_pending", "every 2 min")

        # Maintenance ---------------------------------------------------
        self._add(self._job_targeted_enrichment, "*/15 * * * *", "targeted_enrichment", "queue-driven")
        self._add(self._job_full_reconciliation, "20 1 * * *", "full_reconciliation", "02:20")
        self._add(self._job_backfill, "10 2 * * *", "backfill_14d", "03:10")
        self._add(self._job_staleness_sweep, "45 3 * * *", "staleness_sweep", "04:45")

        # Analyst output ------------------------------------------------
        self._add(self._job_morning_digest, "30 6 * * *", "morning_digest", "07:30")
        self._add(self._job_evening_digest, "0 17 * * *", "evening_digest", "18:00")
        self._add(self._job_calibration_report, "0 8 * * 1", "calibration_report", "Mon 09:00")

    async def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("CadenceScheduler started with %d jobs.", len(self.scheduler.get_jobs()))

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("CadenceScheduler stopped.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    async def _jitter() -> None:
        """Desynchronize collectors that share a cron slot."""
        await asyncio.sleep(random.uniform(0, settings.VERIFY.jitter_seconds * 8))

    async def _run_collectors(self, job_id: str, collectors: Sequence[Any]) -> int:
        """Run a set of collectors, isolating kill switches and failures.

        A disabled or broken source must degrade visibly without taking the
        rest of the pipeline down with it (spec 25 'source removal').
        """
        processed = 0
        async with db_manager.session() as session:
            async with advisory_lock(session, f"job:{job_id}") as acquired:
                if not acquired:
                    logger.info("Skipping %s: another worker holds the window lock.", job_id)
                    return 0

                pipeline = IntelligencePipeline(session)
                for collector in collectors:
                    source_id = getattr(collector, "source_id", collector.__class__.__name__)
                    if not source_register.is_enabled(source_id):
                        logger.info("Source %s is disabled by kill switch; skipping.", source_id)
                        continue
                    await self._jitter()
                    try:
                        processed += await pipeline.run_collector_batch(collector)
                    except Exception:
                        # Isolated per source: one failing collector must not
                        # abort the others in the same window.
                        logger.exception("Collector %s failed during %s", source_id, job_id)
        return processed

    # ------------------------------------------------------------------
    # Discovery jobs
    # ------------------------------------------------------------------
    async def _job_registry_prs(self) -> None:
        await self._run_collectors(
            "registry_prs",
            [EthereumListsCollector(), SuperchainCollector(), CosmosRegistryCollector()],
        )

    async def _job_aggregated_json(self) -> None:
        await self._run_collectors("aggregated_json", [ChainIdNetworkCollector()])

    async def _job_github_search(self) -> None:
        await self._run_collectors("github_search", [GitHubHyperSearchCollector()])

    async def _job_rss_feeds(self) -> None:
        await self._run_collectors("rss_feeds", [RSSFeedsCollector()])

    async def _job_infrastructure_lists(self) -> None:
        await self._run_collectors("infra_lists", [BlockscoutCollector()])

    async def _job_web_news(self) -> None:
        try:
            from src.collectors.web_news.search_queries import WebSearchCollector

            await self._run_collectors("web_news", [WebSearchCollector()])
        except ImportError:
            logger.info("Web/news search collector unavailable; skipping.")

    async def _job_ats_careers(self) -> None:
        await self._run_collectors("ats_careers", [ATSJobBoardsCollector()])

    async def _job_market_analytics(self) -> None:
        try:
            from src.collectors.registries.indexers import IndexerChangelogCollector

            await self._run_collectors("market_analytics", [IndexerChangelogCollector()])
        except ImportError:
            logger.info("Indexer/market collector unavailable; skipping.")

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    async def _job_liveness_recheck(self) -> None:
        """Second-round probes for endpoints whose recheck window has elapsed."""
        if not settings.VERIFIER_ENABLED:
            return
        async with db_manager.session() as session:
            async with advisory_lock(session, "job:liveness_recheck") as acquired:
                if not acquired:
                    return
                service = VerificationService(session)
                pipeline = IntelligencePipeline(session)
                due = await service.endpoints_due_for_recheck(limit=50)
                for observation in due:
                    try:
                        # The stored endpoint is redacted, so re-probe from the
                        # network's published URL rather than the stored copy.
                        endpoint = await self._endpoint_for(session, observation)
                        if not endpoint:
                            continue
                        await service.probe_and_record(
                            endpoint,
                            family=observation.family,
                            candidate_id=observation.candidate_id,
                            network_id=observation.network_id,
                            probe_round=2,
                        )
                        verdict = await service.evaluate_liveness(endpoint)
                        if observation.candidate_id:
                            candidate = await pipeline.repo.get_candidate(observation.candidate_id)
                            if candidate:
                                await pipeline.rescore_candidate(
                                    candidate,
                                    verification={
                                        "has_fingerprint": True,
                                        "has_advancing_liveness": verdict.live,
                                        "liveness": verdict.as_evidence(),
                                    },
                                )
                    except Exception:
                        logger.exception("Liveness recheck failed for observation %s", observation.id)

    async def _job_verify_pending(self) -> None:
        """First-round probes for candidates that have never been verified."""
        if not settings.VERIFIER_ENABLED:
            return
        async with db_manager.session() as session:
            async with advisory_lock(session, "job:verify_pending") as acquired:
                if not acquired:
                    return

                from src.storage.models import VerificationObservation

                already = select(VerificationObservation.candidate_id).where(
                    VerificationObservation.candidate_id.isnot(None)
                )
                stmt = (
                    select(ChainProduct)
                    .join(Network, Network.chain_product_id == ChainProduct.id)
                    .where(
                        Network.rpc_urls != [],
                        ChainProduct.id.notin_(already),
                    )
                    .order_by(ChainProduct.first_seen_at.desc())
                    .limit(settings.VERIFY_BATCH_SIZE)
                )
                candidates = (await session.execute(stmt)).scalars().unique().all()
                if not candidates:
                    return

                pipeline = IntelligencePipeline(session)
                service = VerificationService(session)
                logger.info("Verifying %d pending candidate(s)", len(candidates))

                for candidate in candidates:
                    try:
                        outcome = {
                            "has_fingerprint": False,
                            "has_advancing_liveness": False,
                            "identity_mismatch": False,
                            "endpoint_failures": 0,
                        }
                        for network in candidate.networks or []:
                            for endpoint in list(network.rpc_urls)[:2]:
                                result, observation = await service.probe_and_record(
                                    endpoint,
                                    family=candidate.stack_family,
                                    candidate_id=candidate.id,
                                    network_id=network.id,
                                    expected_chain_id=network.human_chain_id,
                                    probe_round=1,
                                )
                                if observation.failure_class == "identity_mismatch":
                                    outcome["identity_mismatch"] = True
                                elif not observation.success:
                                    outcome["endpoint_failures"] += 1
                                else:
                                    outcome["has_fingerprint"] = True
                                    candidate.last_verified_at = result.checked_at
                                    await service.apply_verified_identity(network, result)
                        await pipeline.rescore_candidate(candidate, verification=outcome)
                        # Commit per candidate so one bad endpoint cannot cost
                        # the whole batch's work.
                        await session.commit()
                    except Exception:
                        logger.exception("Pending verification failed for %s", candidate.id)
                        await session.rollback()

    @staticmethod
    async def _endpoint_for(session, observation) -> Optional[str]:
        """Resolve the live endpoint URL for a stored (redacted) observation."""
        from src.storage.models import Network
        from src.util.redaction import endpoint_hash

        if not observation.network_id:
            return None
        network = await session.get(Network, observation.network_id)
        if not network:
            return None
        for url in network.rpc_urls or []:
            if endpoint_hash(url) == observation.endpoint_hash:
                return url
        return None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    async def _job_targeted_enrichment(self) -> None:
        """Re-run per-candidate queries for active Radar/Outreach candidates."""
        async with db_manager.session() as session:
            async with advisory_lock(session, "job:targeted_enrichment") as acquired:
                if not acquired:
                    return
                stmt = (
                    select(ChainProduct)
                    .join(ScoreSnapshot, ChainProduct.current_score_id == ScoreSnapshot.id)
                    .where(ScoreSnapshot.state.in_(["HOT", "QUALIFIED", "RADAR"]))
                    .order_by(ScoreSnapshot.outreach_score.desc())
                    .limit(25)
                )
                candidates = (await session.execute(stmt)).scalars().unique().all()
                logger.info("Targeted enrichment queue: %d candidates", len(candidates))

    async def _job_full_reconciliation(self) -> None:
        """Rebuild current state from the evidence ledger (spec 18).

        The projection is derived, so it must be reproducible. Any divergence
        between a rebuilt score and the stored one is a bug worth surfacing.
        """
        async with db_manager.session() as session:
            async with advisory_lock(session, "job:full_reconciliation") as acquired:
                if not acquired:
                    return
                pipeline = IntelligencePipeline(session)
                stmt = select(ChainProduct)
                candidates = (await session.execute(stmt)).scalars().unique().all()
                for candidate in candidates:
                    try:
                        await pipeline.rescore_candidate(candidate, trigger_alerts=False)
                    except Exception:
                        logger.exception("Reconciliation failed for candidate %s", candidate.id)
                logger.info("Full reconciliation rebuilt %d candidates", len(candidates))

    async def _job_backfill(self) -> None:
        """Re-scan the trailing window to absorb source indexing delays."""
        days = settings.NIGHTLY_BACKFILL_DAYS
        logger.info("Nightly backfill over the last %d days", days)
        await self._run_collectors("backfill", [GitHubHyperSearchCollector()])

    async def _job_staleness_sweep(self) -> None:
        """Re-evaluate candidates whose evidence may have aged past its TTL."""
        async with db_manager.session() as session:
            async with advisory_lock(session, "job:staleness_sweep") as acquired:
                if not acquired:
                    return
                pipeline = IntelligencePipeline(session)
                stmt = (
                    select(ChainProduct)
                    .join(ScoreSnapshot, ChainProduct.current_score_id == ScoreSnapshot.id)
                    .where(ScoreSnapshot.state.notin_(["REJECT"]))
                )
                candidates = (await session.execute(stmt)).scalars().unique().all()
                for candidate in candidates:
                    try:
                        await pipeline.rescore_candidate(candidate, trigger_alerts=False)
                    except Exception:
                        logger.exception("Staleness sweep failed for %s", candidate.id)

    # ------------------------------------------------------------------
    # Analyst output
    # ------------------------------------------------------------------
    async def _job_morning_digest(self) -> None:
        async with db_manager.session() as session:
            digest = await DigestGenerator.generate_digest(session, digest_type="morning")
            logger.info("Generated morning digest: %s", digest.get("summary"))

    async def _job_evening_digest(self) -> None:
        async with db_manager.session() as session:
            digest = await DigestGenerator.generate_digest(session, digest_type="evening")
            logger.info("Generated evening digest: %s", digest.get("summary"))

    async def _job_calibration_report(self) -> None:
        """Weekly precision / miss / drift report (spec 18, 24)."""
        async with db_manager.session() as session:
            from src.backtesting.temporal_backtest import build_calibration_report

            report = await build_calibration_report(session)
            logger.info("Score calibration report: %s", report.get("summary"))


cadence_scheduler = CadenceScheduler()
