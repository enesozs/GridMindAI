from datetime import date, datetime, timedelta, timezone

import polars as pl

from gridmind.features.calendar import calendar_table
from gridmind.panel import hourly_panel

UTC = timezone.utc


def test_missing_hours_become_visible_rows():
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    ts = [t0 + timedelta(minutes=15 * i) for i in range(4)] + [t0 + timedelta(hours=2, minutes=15 * i) for i in range(4)]
    qh = pl.DataFrame({
        "zone_id": "Z", "metric": "m", "timestamp_utc": ts, "resolution_minutes": 15,
        "value_mw": [1.0] * 8, "source_created_utc": [t0] * 8,
    }, schema_overrides={"timestamp_utc": pl.Datetime("us", "UTC"), "source_created_utc": pl.Datetime("us", "UTC")})
    p = hourly_panel(qh)
    assert p.height == 3
    assert p["is_missing"].to_list() == [False, True, False]
    assert p["value_mw"].to_list() == [1.0, None, 1.0]


def test_calendar_regional_and_national_holidays():
    cal = calendar_table(date(2025, 6, 18), date(2025, 12, 26)).to_dicts()
    by = {r["date_local"]: r for r in cal}
    assert by[date(2025, 12, 25)]["is_national_holiday"]
    corpus = by[date(2025, 6, 19)]  # Corpus Christi: BW, BY, HE, NW, RP, SL (+ parts)
    assert 0.4 < corpus["holiday_pop_share"] < 0.8 and not corpus["is_national_holiday"]
    assert by[date(2025, 6, 20)]["is_bridge_day"]  # Friday after Corpus Christi
    assert by[date(2025, 12, 24)]["is_christmas_period"]
