"""Market-day and interval arithmetic.

Canonical convention: every interval is identified by its START in UTC, half-open
[start, start + resolution). A market "delivery day" is a local calendar day in the
bidding zone's time zone, which is 23, 24 or 25 hours long because of DST.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


def delivery_day_bounds_utc(day: date, tz: str) -> tuple[datetime, datetime]:
    """UTC [start, end) of the local calendar day `day` in time zone `tz`."""
    zone = ZoneInfo(tz)
    start_local = datetime(day.year, day.month, day.day, tzinfo=zone)
    nxt = day + timedelta(days=1)
    end_local = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def delivery_day_hours(day: date, tz: str) -> int:
    start, end = delivery_day_bounds_utc(day, tz)
    return int((end - start).total_seconds() // 3600)


def hourly_starts_utc(day: date, tz: str) -> list[datetime]:
    """UTC start of every hour in the local delivery day (23/24/25 values)."""
    start, end = delivery_day_bounds_utc(day, tz)
    out, t = [], start
    while t < end:
        out.append(t)
        t += timedelta(hours=1)
    return out


def local_at(day: date, hour: int, minute: int, tz: str) -> datetime:
    """A wall-clock time on `day` in `tz`, returned as an aware UTC datetime.

    Raises ValueError for nonexistent wall-clock times (spring-forward gap), so issue
    rules can never silently land on a time that did not exist.
    """
    zone = ZoneInfo(tz)
    naive = datetime(day.year, day.month, day.day, hour, minute)
    aware = naive.replace(tzinfo=zone)
    roundtrip = aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if roundtrip != naive:
        raise ValueError(f"{naive} does not exist in {tz} (DST gap)")
    return aware.astimezone(UTC)
