"""Chain vitality: is this project still alive? (spec 01 dormant/abandoned gate)

The spec hard-blocks candidates with "no code, endpoint, announcement or
community activity within the configured staleness window", but that judgement
needs evidence from the places a living project inevitably leaves traces: the
chain itself, its repositories, its official site, and its public social
accounts.

Two principles keep this honest.

*Silence must be observed, not assumed.* A channel we never managed to read is
`UNKNOWN`, which is not the same as a channel that has gone quiet. Treating an
unread channel as dead would let a rate limit or a parser bug bury a healthy
project.

*The chain outranks the marketing.* A network producing blocks is alive even if
its Twitter account has been quiet for months; the reverse is not true. So the
channels are weighted, and a live chain cannot be dragged to DORMANT by social
silence alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.config import settings
from src.util.timeutil import age_days, to_utc, utcnow


class VitalityStatus(str, Enum):
    ACTIVE = "active"
    SLOWING = "slowing"
    DORMANT = "dormant"
    DEAD = "dead"
    UNKNOWN = "unknown"


# Relative importance of each channel. The chain and the code are what make a
# project real; social reach is a marketing signal that follows, not leads.
CHANNEL_WEIGHTS: Dict[str, float] = {
    "rpc": 0.30,
    "explorer": 0.20,
    "github": 0.25,
    "website": 0.10,
    "blog": 0.05,
    "x": 0.04,
    "farcaster": 0.03,
    "bluesky": 0.02,
    "discord": 0.01,
    "telegram": 0.00,
}

# Channels that constitute hard technical proof of life.
TECHNICAL_CHANNELS = {"rpc", "explorer"}


@dataclass
class ChannelActivity:
    """One channel's last-observed activity."""

    channel: str
    last_activity_at: Optional[datetime]
    last_activity_kind: Optional[str] = None
    age_days: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    observed: bool = True

    @property
    def status(self) -> VitalityStatus:
        if not self.observed or self.age_days is None:
            return VitalityStatus.UNKNOWN
        thresholds = settings.VITALITY.thresholds_days
        if self.age_days <= thresholds["active"]:
            return VitalityStatus.ACTIVE
        if self.age_days <= thresholds["slowing"]:
            return VitalityStatus.SLOWING
        if self.age_days <= thresholds["dormant"]:
            return VitalityStatus.DORMANT
        return VitalityStatus.DEAD


@dataclass
class VitalityAssessment:
    """Whether a candidate is worth an analyst's time right now."""

    status: VitalityStatus
    score: float                       # 0-100, higher is more alive
    channels: List[ChannelActivity] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    observed_channel_count: int = 0
    most_recent_activity_at: Optional[datetime] = None
    technical_liveness: bool = False

    @property
    def is_dormant_or_dead(self) -> bool:
        return self.status in (VitalityStatus.DORMANT, VitalityStatus.DEAD)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "score": round(self.score, 2),
            "technical_liveness": self.technical_liveness,
            "observed_channels": self.observed_channel_count,
            "most_recent_activity_at": (
                self.most_recent_activity_at.isoformat() if self.most_recent_activity_at else None
            ),
            "reasons": self.reasons,
            "channels": [
                {
                    "channel": c.channel,
                    "status": c.status.value,
                    "last_activity_at": (
                        c.last_activity_at.isoformat() if c.last_activity_at else None
                    ),
                    "last_activity_kind": c.last_activity_kind,
                    "age_days": round(c.age_days, 1) if c.age_days is not None else None,
                    "metrics": c.metrics,
                }
                for c in self.channels
            ],
        }


def _decay(age: float, half_life: float) -> float:
    """Freshness in [0, 1] halving every `half_life` days."""
    if age <= 0:
        return 1.0
    return 0.5 ** (age / max(half_life, 0.5))


class VitalityClassifier:
    """Turns per-channel activity observations into a single verdict."""

    def assess(
        self,
        snapshots: Sequence[Any],
        now: Optional[datetime] = None,
        chain_is_advancing: Optional[bool] = None,
    ) -> VitalityAssessment:
        """Assess vitality from the newest snapshot per channel.

        `chain_is_advancing` comes from the two-observation liveness proof and
        outranks everything else: a chain demonstrably producing blocks is not
        dormant, whatever its social accounts are doing.
        """
        now = now or utcnow()
        thresholds = settings.VITALITY.thresholds_days
        half_life = float(settings.VITALITY.freshness_half_life_days)

        # Keep only the most recent observation per channel.
        newest: Dict[str, Any] = {}
        for snapshot in snapshots:
            existing = newest.get(snapshot.channel)
            if existing is None or to_utc(snapshot.observed_at) > to_utc(existing.observed_at):
                newest[snapshot.channel] = snapshot

        channels: List[ChannelActivity] = []
        for channel, snapshot in newest.items():
            last = to_utc(snapshot.last_activity_at) if snapshot.last_activity_at else None
            channels.append(
                ChannelActivity(
                    channel=channel,
                    last_activity_at=last,
                    last_activity_kind=snapshot.last_activity_kind,
                    age_days=age_days(last, now) if last else None,
                    metrics=self._metrics_of(snapshot),
                    observed=True,
                )
            )

        channels.sort(key=lambda c: CHANNEL_WEIGHTS.get(c.channel, 0.0), reverse=True)
        dated = [c for c in channels if c.age_days is not None]

        if not dated:
            return VitalityAssessment(
                status=VitalityStatus.UNKNOWN,
                score=0.0,
                channels=channels,
                reasons=[
                    "No channel activity has been observed yet. This is unknown, "
                    "not dormant: absence of observation is not evidence of silence."
                ],
                observed_channel_count=len(channels),
            )

        # Weighted freshness across whatever we could actually observe.
        total_weight = sum(CHANNEL_WEIGHTS.get(c.channel, 0.01) for c in dated)
        weighted = sum(
            CHANNEL_WEIGHTS.get(c.channel, 0.01) * _decay(c.age_days, half_life) for c in dated
        )
        score = 100.0 * (weighted / total_weight) if total_weight else 0.0

        most_recent = max(c.last_activity_at for c in dated if c.last_activity_at)
        newest_age = age_days(most_recent, now)

        technical = [c for c in dated if c.channel in TECHNICAL_CHANNELS]
        technical_live = bool(chain_is_advancing) or any(
            c.status == VitalityStatus.ACTIVE for c in technical
        )

        status = self._status_for(newest_age, thresholds)
        reasons: List[str] = []

        if chain_is_advancing:
            # Verified block progression is the strongest evidence available.
            if status in (VitalityStatus.DORMANT, VitalityStatus.DEAD):
                status = VitalityStatus.SLOWING
                reasons.append(
                    "Chain is verifiably producing blocks, so it is not dormant despite "
                    "quiet public channels."
                )
            score = max(score, 60.0)

        reasons.append(
            f"Most recent observed activity was {newest_age:.1f} days ago "
            f"({max(dated, key=lambda c: c.last_activity_at or now).channel})."
        )

        engineering = next((c for c in dated if c.channel == "github"), None)
        if engineering and engineering.age_days is not None:
            if engineering.status == VitalityStatus.ACTIVE:
                reasons.append(
                    f"Repository activity within {engineering.age_days:.0f} days indicates the "
                    "team is still shipping."
                )
            elif engineering.status in (VitalityStatus.DORMANT, VitalityStatus.DEAD):
                reasons.append(
                    f"No repository activity for {engineering.age_days:.0f} days, which is the "
                    "clearest indicator of an abandoned build."
                )

        unobserved = sorted(set(CHANNEL_WEIGHTS) - set(newest))
        if unobserved:
            reasons.append(
                "Not observed (treated as unknown, not silent): " + ", ".join(unobserved[:6])
            )

        return VitalityAssessment(
            status=status,
            score=min(100.0, max(0.0, score)),
            channels=channels,
            reasons=reasons,
            observed_channel_count=len(channels),
            most_recent_activity_at=most_recent,
            technical_liveness=technical_live,
        )

    @staticmethod
    def _status_for(age: float, thresholds: Dict[str, int]) -> VitalityStatus:
        if age <= thresholds["active"]:
            return VitalityStatus.ACTIVE
        if age <= thresholds["slowing"]:
            return VitalityStatus.SLOWING
        if age <= thresholds["dormant"]:
            return VitalityStatus.DORMANT
        return VitalityStatus.DEAD

    @staticmethod
    def _metrics_of(snapshot: Any) -> Dict[str, Any]:
        fields = (
            "followers", "stars", "forks", "contributors", "commits_last_30d",
            "releases_last_90d", "posts_last_30d", "open_issues", "block_height",
        )
        metrics = {f: getattr(snapshot, f, None) for f in fields}
        metrics = {k: v for k, v in metrics.items() if v is not None}
        metrics.update(getattr(snapshot, "extra_metrics", None) or {})
        return metrics


vitality_classifier = VitalityClassifier()
