"""Time helpers.

Storage is always UTC (spec 18). Analyst-facing output renders in Africa/Lagos,
which is UTC+1 with no DST, so a fixed offset is exact and avoids depending on
a tz database being present in the container.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WAT = timezone(timedelta(hours=1), name="WAT")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    """Normalize any datetime to aware UTC.

    Naive values are assumed to be UTC already: every writer here stores UTC,
    and some drivers hand back naive datetimes for timestamp columns.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_wat(value: datetime) -> datetime:
    """Render a stored timestamp in the analyst-facing timezone."""
    return to_utc(value).astimezone(WAT)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return to_utc(value).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating the trailing 'Z' form."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return to_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def observed_bucket(value: datetime, minutes: int = 60) -> str:
    """Coarse time bucket completing the evidence dedup key (spec 21).

    Identical content re-observed inside one bucket is the same evidence row;
    the same content seen in a later bucket is a genuine re-observation, which
    is what keeps freshness and liveness re-checks meaningful.
    """
    seconds = max(1, minutes) * 60
    epoch_buckets = int(to_utc(value).timestamp()) // seconds
    return f"{minutes}m:{epoch_buckets}"


def days_between(later: datetime, earlier: datetime) -> float:
    return (to_utc(later) - to_utc(earlier)).total_seconds() / 86400.0


def age_days(value: datetime, now: datetime | None = None) -> float:
    return days_between(now or utcnow(), value)
