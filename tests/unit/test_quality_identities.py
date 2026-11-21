"""SYNTHETIC panels for the accounting-identity checks in the quality report."""

from datetime import datetime, timedelta, timezone

import polars as pl

from gridmind.quality.report import identity_check

UTC = timezone.utc


def _panel(residual_offset: float = 0.0, solar_scale: float = 1.0) -> pl.DataFrame:
    t = [datetime(2025, 6, 1, tzinfo=UTC) + timedelta(hours=h) for h in range(48)]
    rows = []
    for i, ts in enumerate(t):
        load, won, woff, sol = 60_000.0, 10_000.0 + i, 3_000.0, 20_000.0 if 6 <= ts.hour <= 18 else 0.0
        residual = load - won - woff - sol + residual_offset
        for m, v in [("actual_total_load", load), ("gen_wind_onshore", won), ("gen_wind_offshore", woff),
                     ("gen_solar", sol * solar_scale), ("residual_load", residual)]:
            rows.append(("DE_LU", m, ts, v))
    return pl.DataFrame(rows, schema={"zone_id": pl.String, "metric": pl.String,
                                      "timestamp_utc": pl.Datetime("us", "UTC"), "value_mw": pl.Float64},
                        orient="row")


RHS = {"actual_total_load": 1, "gen_wind_onshore": -1, "gen_wind_offshore": -1, "gen_solar": -1}


def test_identity_holds():
    r = identity_check(_panel(), "DE_LU", "residual_load", RHS)
    assert r["hours_compared"] == 48 and r["p99_abs_diff_mw"] == 0.0 and r["hours_over_1pct_of_mean_level"] == 0


def test_identity_detects_unit_error():
    # Solar mistakenly 4x (e.g. MWh-per-15-min treated as MW the wrong way) breaks the identity in daylight.
    r = identity_check(_panel(solar_scale=4.0), "DE_LU", "residual_load", RHS)
    assert r["hours_over_1pct_of_mean_level"] > 0 and r["p99_abs_diff_mw"] > 10_000


def test_identity_reports_missing_series():
    p = _panel().filter(pl.col("metric") != "gen_solar")
    r = identity_check(p, "DE_LU", "residual_load", RHS)
    assert r["hours_compared"] == 0 and r["missing_series"] == ["gen_solar"]
