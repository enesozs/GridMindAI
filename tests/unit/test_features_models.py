"""SYNTHETIC data tests for the feature builder (leakage guards) and metrics."""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from gridmind.analytics.metrics import diebold_mariano, pinball, probabilistic_metrics
from gridmind.features.build import assert_point_in_time, build_features
from gridmind.features.calendar import calendar_table
from gridmind.providers.weather import DE_LU_POINTS

UTC = timezone.utc


def _synthetic_inputs(first: date, days: int):
    t0 = datetime(first.year, first.month, first.day, tzinfo=UTC) - timedelta(days=20)
    hours = [t0 + timedelta(hours=i) for i in range(24 * (days + 22))]
    # load = 50 GW + 10 GW * daily sine; value encodes its own timestamp for leak checks
    load = [50000 + 10000 * np.sin(2 * np.pi * h.hour / 24) + i * 1e-3 for i, h in enumerate(hours)]
    panel = pl.DataFrame({
        "zone_id": "DE_LU", "metric": "actual_total_load", "timestamp_utc": hours, "value_mw": load,
    }, schema_overrides={"timestamp_utc": pl.Datetime("us", "UTC")})
    panel = pl.concat([panel, panel.with_columns(metric=pl.lit("tso_day_ahead_load_forecast"))])
    # Fixed-lead archive (like Open-Meteo previous_day2): one 48-h-ahead value per valid hour.
    valid = [datetime(first.year, first.month, first.day, tzinfo=UTC) + timedelta(hours=h - 48)
             for h in range(24 * (days + 4))]
    vint = pl.DataFrame([
        (v - timedelta(hours=48), v, 48.0, p.location_id, 10.0, 100.0, 50.0, 1.0)
        for v in valid for p in DE_LU_POINTS
    ], schema={"weather_model_run": pl.Datetime("us", "UTC"), "valid_at_utc": pl.Datetime("us", "UTC"),
               "forecast_lead_hours": pl.Float64, "location": pl.String, "temperature_2m": pl.Float64,
               "downward_short_wave_radiation_flux_surface": pl.Float64, "total_cloud_cover_atmosphere": pl.Float64,
               "wind_speed_10m": pl.Float64}, orient="row")
    cal = calendar_table(first - timedelta(days=30), first + timedelta(days=days + 5))
    return panel, vint, cal


def test_features_use_only_information_known_at_issue():
    first = date(2025, 3, 25)
    panel, vint, cal = _synthetic_inputs(first, 10)
    f = build_features(panel, cal, vint, first, first + timedelta(days=9))
    assert_point_in_time(f)
    # lag_d7 must equal load exactly 7 local days earlier (checked on a winter-time day)
    row = f.filter(pl.col("delivery_day") == date(2025, 3, 27)).sort("valid_at_utc").row(5, named=True)
    src = panel.filter((pl.col("metric") == "actual_total_load")
                       & (pl.col("timestamp_utc") == row["valid_at_utc"] - timedelta(days=7)))["value_mw"][0]
    assert row["lag_d7"] == pytest.approx(src)
    # the recent-level window ends before the issue time
    assert (f["last_known_load_end"] < f["issue_time_utc"]).all()
    # weather for every hour was predicted 48 h earlier
    d27 = f.filter(pl.col("delivery_day") == date(2025, 3, 27))
    assert (d27["valid_at_utc"] - d27["weather_model_run"] == timedelta(hours=48)).all()
    assert d27["wx_t2m"].null_count() == 0
    # DST day has 23 rows
    assert f.filter(pl.col("delivery_day") == date(2025, 3, 30)).height == 23


def test_point_in_time_guard_catches_late_runs():
    first = date(2025, 1, 10)
    panel, vint, cal = _synthetic_inputs(first, 3)
    f = build_features(panel, cal, vint, first, first + timedelta(days=2))
    late = f.with_columns(weather_model_run=pl.col("issue_time_utc"))
    with pytest.raises(AssertionError):
        assert_point_in_time(late)


def test_metrics():
    y = np.array([10.0, 20.0, 30.0])
    assert pinball(y, y, 0.5) == 0
    df = pl.DataFrame({"y": y, "q05": y - 1, "q25": y, "q50": y, "q75": y, "q95": y + 1})
    m = probabilistic_metrics(df)
    assert m["coverage_90"] == 1.0 and m["width_90_mw"] == 2.0
    rng = np.random.default_rng(0)
    better = rng.normal(0, 1, 400)
    worse = better * 3
    assert diebold_mariano(better, worse)["dm_stat"] < -2
