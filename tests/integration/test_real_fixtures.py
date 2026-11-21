"""Contract checks on small REAL extracts (see tests/fixtures/README.md for licences)."""

from datetime import date, timedelta
from pathlib import Path

import polars as pl

from gridmind.contracts.issue_time import WEATHER_AVAILABILITY_LAG, IssueRule
from gridmind.providers.openmeteo import DATASET as OM_DATASET
from gridmind.quality.resample import to_hourly_mean_mw

FIX = Path(__file__).parents[1] / "fixtures"


def _smard(metric: str) -> pl.DataFrame:
    return pl.read_csv(FIX / f"smard_{metric}_DE-LU_2025-03-30_31.csv", try_parse_dates=True).with_columns(
        pl.col("timestamp_utc").dt.convert_time_zone("UTC")
    )


def test_smard_dst_day_has_92_quarter_hours_and_23_hours():
    df = _smard("actual_total_load")
    assert df.height == 92 + 96
    hourly = to_hourly_mean_mw(df.select("timestamp_utc", "resolution_minutes", pl.col("value_mw").alias("value")))
    assert hourly.height == 23 + 24
    assert not hourly["is_partial_coverage"].any()


def test_smard_load_is_plausible_power_in_mw():
    # German load is roughly 35-80 GW; if MWh-per-15-min were mistaken for MW this would be ~4x too small.
    for m in ["actual_total_load", "tso_day_ahead_load_forecast"]:
        mw = _smard(m)["value_mw"]
        assert 30_000 < mw.min() and mw.max() < 90_000


def test_openmeteo_fixed_lead_weather_is_available_at_issue():
    """Every 48-h-lead value for delivery day D was predicted before D-1 10:00 (plus publication lag)."""
    w = pl.read_csv(FIX / "openmeteo_previous_day2_DE-LU_2025-03-30_31.csv", try_parse_dates=True)
    rule = IssueRule()
    lag = WEATHER_AVAILABILITY_LAG[OM_DATASET]
    assert (w["forecast_lead_hours"] == 48.0).all()
    assert (w["valid_at_utc"] - w["weather_model_run"] == timedelta(hours=48)).all()
    for d in [date(2025, 3, 30), date(2025, 3, 31)]:
        start, end = (t.replace(tzinfo=None) for t in rule.target_window(d))
        g = w.filter((pl.col("valid_at_utc").dt.replace_time_zone(None) >= start)
                     & (pl.col("valid_at_utc").dt.replace_time_zone(None) < end))
        issue = rule.issue_time(d).replace(tzinfo=None)
        assert g["location"].n_unique() == 13
        assert g["valid_at_utc"].n_unique() == int((end - start) / timedelta(hours=1))  # 23 h on the DST day
        assert (g["weather_model_run"].dt.replace_time_zone(None) + lag <= issue).all()
        assert g["temperature_2m"].null_count() == 0
