"""Lifecycle stage transitions and multi-timestamp tracking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from src.config import settings
from src.core.types import LifecycleStage
from src.storage.models import ChainProduct


class LifecycleManager:
    """Manages the multi-timestamp model and stage transitions for a blockchain candidate."""

    @staticmethod
    def _to_datetime(val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        if isinstance(val, str):
            try:
                from dateutil import parser as dt_parser
                dt = dt_parser.parse(val)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        return None

    @classmethod
    def update_timestamps_from_claims(cls, chain: ChainProduct, claims: dict) -> None:
        """Updates specific timestamp fields based on evidence claims and syncs earliest first_seen_at."""
        if not claims or not isinstance(claims, dict):
            return

        if "repo_created_at" in claims and not chain.repo_created_at:
            chain.repo_created_at = cls._to_datetime(claims["repo_created_at"])
        if "first_commit_at" in claims and not chain.first_commit_at:
            chain.first_commit_at = cls._to_datetime(claims["first_commit_at"])
        if "domain_first_seen_at" in claims and not chain.domain_first_seen_at:
            chain.domain_first_seen_at = cls._to_datetime(claims["domain_first_seen_at"])
        if "registry_pr_opened_at" in claims and not chain.registry_pr_opened_at:
            chain.registry_pr_opened_at = cls._to_datetime(claims["registry_pr_opened_at"])
        if "registry_merged_at" in claims and not chain.registry_merged_at:
            chain.registry_merged_at = cls._to_datetime(claims["registry_merged_at"])
        if "testnet_announced_at" in claims and not chain.testnet_announced_at:
            chain.testnet_announced_at = cls._to_datetime(claims["testnet_announced_at"])
        if "mainnet_announced_for" in claims:
            chain.mainnet_announced_for = cls._to_datetime(claims["mainnet_announced_for"])
        if "mainnet_live_at" in claims and not chain.mainnet_live_at:
            chain.mainnet_live_at = cls._to_datetime(claims["mainnet_live_at"])

        # Determine the earliest verified timestamp
        candidates = [
            chain.first_seen_at,
            chain.repo_created_at,
            chain.first_commit_at,
            chain.domain_first_seen_at,
            chain.registry_pr_opened_at,
            chain.testnet_announced_at,
            cls._to_datetime(claims.get("published_at")),
            cls._to_datetime(claims.get("first_seen_at")),
            cls._to_datetime(claims.get("created_at")),
        ]
        valid_dates = [d for d in candidates if d is not None]
        if valid_dates:
            chain.first_seen_at = min(valid_dates)

    @staticmethod
    def compute_current_stage(
        chain: ChainProduct,
        networks: Optional[List[Any]] = None,
        has_incentive: bool = False,
        is_live_mainnet: bool = False,
    ) -> LifecycleStage:
        """Computes current deterministic lifecycle stage from evidence."""
        now = datetime.now(timezone.utc)

        # S5 / S6 Check: Mainnet live
        if chain.mainnet_live_at or is_live_mainnet:
            live_at = chain.mainnet_live_at or now
            cutoff_date = now - timedelta(days=settings.EARLY_MAINNET_DAYS)
            if live_at >= cutoff_date:
                return LifecycleStage.S5_EARLY_MAINNET
            else:
                return LifecycleStage.S6_ESTABLISHED_ARCHIVED

        # S4 Check: Mainnet announced
        if chain.mainnet_announced_for:
            return LifecycleStage.S4_MAINNET_ANNOUNCED

        # S3 Check: Incentivized testnet
        if has_incentive:
            return LifecycleStage.S3_INCENTIVIZED_TESTNET

        # Safely inspect networks without triggering lazy load
        net_list = networks if networks is not None else (chain.__dict__.get("networks") or [])

        # S2 Check: Public testnet
        if chain.testnet_announced_at or any(getattr(net, "environment", "") == "testnet" and getattr(net, "is_public", True) for net in net_list):
            return LifecycleStage.S2_PUBLIC_TESTNET

        # S1 Check: Devnet / Prototype / Registry PR
        if chain.registry_pr_opened_at or chain.repo_created_at or any(getattr(net, "environment", "") == "devnet" for net in net_list):
            return LifecycleStage.S1_DEVNET_PROTOTYPE

        # S0 Default: Research hint
        return LifecycleStage.S0_RESEARCH_HINT
