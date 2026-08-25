"""Scheduler managing cron execution schedules in UTC / Africa/Lagos."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
from src.storage.database import db_manager

logger = logging.getLogger(__name__)


class CadenceScheduler:
    """Manages scheduled discovery, liveness checks, digests, and reconciliation."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=settings.STORAGE_TIMEZONE)
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        # 1. Registry PRs (Every 10 min)
        self.scheduler.add_job(
            self._job_registry_prs,
            CronTrigger.from_crontab("*/10 * * * *"),
            id="registry_prs",
            replace_existing=True,
        )

        # 2. Aggregated JSON registries (Every 15 min)
        self.scheduler.add_job(
            self._job_aggregated_json,
            CronTrigger.from_crontab("3,18,33,48 * * * *"),
            id="aggregated_json",
            replace_existing=True,
        )

        # 3. GitHub broad repo search (Every 30 min)
        self.scheduler.add_job(
            self._job_github_search,
            CronTrigger.from_crontab("7,37 * * * *"),
            id="github_search",
            replace_existing=True,
        )

        # 4. RSS/Atom & RaaS Blogs (Every 15 min)
        self.scheduler.add_job(
            self._job_rss_feeds,
            CronTrigger.from_crontab("*/15 * * * *"),
            id="rss_feeds",
            replace_existing=True,
        )

        # 5. ATS / Careers (Every 6 h)
        self.scheduler.add_job(
            self._job_ats_careers,
            CronTrigger.from_crontab("40 */6 * * *"),
            id="ats_careers",
            replace_existing=True,
        )

        # 6. Morning Digest (07:30 WAT / 06:30 UTC)
        self.scheduler.add_job(
            self._job_morning_digest,
            CronTrigger.from_crontab("30 6 * * *"),
            id="morning_digest",
            replace_existing=True,
        )

        # 7. Evening Digest (18:00 WAT / 17:00 UTC)
        self.scheduler.add_job(
            self._job_evening_digest,
            CronTrigger.from_crontab("0 17 * * *"),
            id="evening_digest",
            replace_existing=True,
        )

    async def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("CadenceScheduler started successfully.")

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("CadenceScheduler stopped.")

    # Job Handlers
    async def _job_registry_prs(self) -> None:
        if not source_register.is_enabled("ethereum_lists"):
            return
        async with db_manager.session() as session:
            pipeline = IntelligencePipeline(session)
            await pipeline.run_collector_batch(EthereumListsCollector())
            await pipeline.run_collector_batch(SuperchainCollector())
            await pipeline.run_collector_batch(CosmosRegistryCollector())

    async def _job_aggregated_json(self) -> None:
        if not source_register.is_enabled("chainid_network"):
            return
        async with db_manager.session() as session:
            pipeline = IntelligencePipeline(session)
            await pipeline.run_collector_batch(ChainIdNetworkCollector())

    async def _job_github_search(self) -> None:
        if not source_register.is_enabled("github_hyper_search"):
            return
        async with db_manager.session() as session:
            pipeline = IntelligencePipeline(session)
            await pipeline.run_collector_batch(GitHubHyperSearchCollector())

    async def _job_rss_feeds(self) -> None:
        if not source_register.is_enabled("rss_sitemaps"):
            return
        async with db_manager.session() as session:
            pipeline = IntelligencePipeline(session)
            await pipeline.run_collector_batch(RSSFeedsCollector())

    async def _job_ats_careers(self) -> None:
        if not source_register.is_enabled("ats_job_boards"):
            return
        async with db_manager.session() as session:
            pipeline = IntelligencePipeline(session)
            await pipeline.run_collector_batch(ATSJobBoardsCollector())

    async def _job_morning_digest(self) -> None:
        async with db_manager.session() as session:
            digest = await DigestGenerator.generate_digest(session, digest_type="morning")
            logger.info(f"Generated Morning Digest: {digest['summary']}")

    async def _job_evening_digest(self) -> None:
        async with db_manager.session() as session:
            digest = await DigestGenerator.generate_digest(session, digest_type="evening")
            logger.info(f"Generated Evening Digest: {digest['summary']}")


cadence_scheduler = CadenceScheduler()
