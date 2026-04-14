"""Time and datetime utilities."""

from datetime import UTC, datetime, timedelta

import pytz


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def hours_since(dt: datetime) -> float:
    """Return hours elapsed since a datetime (UTC-aware)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (utcnow() - dt).total_seconds() / 3600


def to_local(dt: datetime, timezone: str) -> datetime:
    """Convert a UTC-aware datetime to a local timezone."""
    tz = pytz.timezone(timezone)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def start_of_day(dt: datetime) -> datetime:
    """Return the start of the day (00:00:00) for a given datetime."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def day_of_year(dt: datetime) -> int:
    """Return the Julian day-of-year (1–366) for extraterrestrial radiation calcs."""
    return dt.timetuple().tm_yday
