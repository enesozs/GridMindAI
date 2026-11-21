"""Point-in-time feature matrix for day-ahead hourly DE-LU load.

One row per (delivery day D, target hour). Every feature is computable at
issue_time = D-1 10:00 Europe/Berlin:

- load lags by LOCAL date/hour: D-7 (and D-14), D-2: all end before the issue time;
- recent level: mean of the last 24 known hours, ending at last_known_load_end;
- weather: the GFS forecast made 48 h before each target hour (Open-Meteo fixed-lead
  archive, population-weighted over 13 points), plus D's daily aggregates;
- calendar: known in advance.

Benchmark/target columns (never features): `y` actual load, `tso_forecast`.
Oracle columns (`oracle_*`, from lead-0 "hindsight" weather) exist only for the labelled
hindsight ablation and are never used by operational models.
"""

from __future__ import annotations

from datetime import date, timedelta, timezone

import numpy as np
import polars as pl

from gridmind.contracts.issue_time import WEATHER_AVAILABILITY_LAG, IssueRule
from gridmind.providers.openmeteo import DATASET as OM_DATASET
from gridmind.providers.weather import DE_LU_POINTS
from gridmind.timeutils import hourly_starts_utc

UTC = timezone.utc
TZ = "Europe/Berlin"
WEIGHTS = {p.location_id: p.weight for p in DE_LU_POINTS}


def _local_keys(df: pl.DataFrame, col: str = "timestamp_utc") -> pl.DataFrame:
    local = pl.col(col).dt.convert_time_zone(TZ)
    return df.with_columns(local_date=local.dt.date(), local_hour=local.dt.hour())


def target_grid(first: date, last: date, rule: IssueRule) -> pl.DataFrame:
    rows = []
    d = first
    while d <= last:
        it = rule.issue_time(d)
        lk = rule.last_known_load_end(d)
        for t in hourly_starts_utc(d, TZ):
            rows.append((d, t, it, lk))
        d += timedelta(days=1)
    df = pl.DataFrame(
        rows,
        schema={"delivery_day": pl.Date, "valid_at_utc": pl.Datetime("us", "UTC"),
                "issue_time_utc": pl.Datetime("us", "UTC"), "last_known_load_end": pl.Datetime("us", "UTC")},
        orient="row",
    )
    df = _local_keys(df, "valid_at_utc").with_columns(
        lead_hours=(pl.col("valid_at_utc") - pl.col("issue_time_utc")).dt.total_minutes() / 60
    )
    # On the 25-h day local hour 2 occurs twice; index occurrences so joins stay 1:1.
    return df.with_columns(hour_occurrence=pl.col("valid_at_utc").rank("ordinal").over("delivery_day", "local_hour")
                           .cast(pl.Int32))


def _series(panel: pl.DataFrame, zone: str, metric: str) -> pl.DataFrame:
    return panel.filter((pl.col("zone_id") == zone) & (pl.col("metric") == metric)).select(
        "timestamp_utc", "value_mw"
    )


def _lag_by_local(grid: pl.DataFrame, load_local: pl.DataFrame, days: int, name: str) -> pl.DataFrame:
    ref = load_local.with_columns(local_date=pl.col("local_date") + pl.duration(days=days)).select(
        "local_date", "local_hour", pl.col("value_mw").alias(name)
    )
    return grid.join(ref, on=["local_date", "local_hour"], how="left")


def _weighted(df: pl.DataFrame, cols: list[str], by: list[str], weights: dict[str, float] | None = None
              ) -> pl.DataFrame:
    weights = weights or WEIGHTS
    df = df.filter(pl.col("location").is_in(list(weights)))
    w = pl.col("location").replace_strict(weights, return_dtype=pl.Float64)
    return df.group_by(by).agg(
        [pl.when(pl.col(c).is_not_null().any())
         .then((pl.col(c) * w).sum() / w.filter(pl.col(c).is_not_null()).sum()).alias(c) for c in cols]
    )


def weather_features_fixed_lead(vintages: pl.DataFrame, grid: pl.DataFrame,
                                weights: dict[str, float] | None = None) -> pl.DataFrame:
    """Fixed-lead archives (e.g. Open-Meteo previous_day2): one forecast per valid hour,
    made a fixed time before it. Join on valid time; keep the nominal run time for audit."""
    cols = [c for c in ["temperature_2m", "downward_short_wave_radiation_flux_surface",
                        "total_cloud_cover_atmosphere", "wind_speed_10m"] if c in vintages.columns]
    w = _weighted(vintages, cols, ["valid_at_utc"], weights).rename(
        {"temperature_2m": "wx_t2m", "downward_short_wave_radiation_flux_surface": "wx_ssrd",
         "total_cloud_cover_atmosphere": "wx_cloud", "wind_speed_10m": "wx_wind"}, strict=False)
    runs = vintages.group_by("valid_at_utc").agg(pl.col("weather_model_run").max())
    g = grid.join(w, on="valid_at_utc", how="left").join(runs, on="valid_at_utc", how="left")
    # Fill NaN (not null) from weighting all-null groups so trees see a proper missing value.
    g = g.with_columns([pl.col(c).fill_nan(None) for c in ["wx_t2m", "wx_ssrd", "wx_cloud", "wx_wind"]
                        if c in g.columns])
    daily = g.group_by("delivery_day").agg(
        wx_t2m_day_mean=pl.col("wx_t2m").mean(), wx_t2m_day_min=pl.col("wx_t2m").min(),
        wx_t2m_day_max=pl.col("wx_t2m").max(), wx_ssrd_day_mean=pl.col("wx_ssrd").mean(),
    )
    return g.join(daily, on="delivery_day", how="left").with_columns(
        wx_hdd=(15.0 - pl.col("wx_t2m_day_mean")).clip(lower_bound=0),
        wx_cdd=(pl.col("wx_t2m_day_mean") - 20.0).clip(lower_bound=0),
    )


def oracle_features(analysis: pl.DataFrame, grid: pl.DataFrame) -> pl.DataFrame:
    cols = [c for c in ["temperature_2m", "downward_short_wave_radiation_flux_surface"] if c in analysis.columns]
    w = _weighted(analysis, cols, ["valid_at_utc"]).rename(
        {"temperature_2m": "oracle_t2m", "downward_short_wave_radiation_flux_surface": "oracle_ssrd"}, strict=False)
    g = grid.join(w, on="valid_at_utc", how="left")
    daily = g.group_by("delivery_day").agg(
        oracle_t2m_day_mean=pl.col("oracle_t2m").mean(), oracle_t2m_day_min=pl.col("oracle_t2m").min(),
        oracle_t2m_day_max=pl.col("oracle_t2m").max())
    return g.join(daily, on="delivery_day", how="left").with_columns(
        oracle_hdd=(15.0 - pl.col("oracle_t2m_day_mean")).clip(lower_bound=0),
        oracle_cdd=(pl.col("oracle_t2m_day_mean") - 20.0).clip(lower_bound=0))


def build_features(
    panel: pl.DataFrame,
    calendar: pl.DataFrame,
    vintages: pl.DataFrame,
    first: date,
    last: date,
    dataset: str = OM_DATASET,
    analysis: pl.DataFrame | None = None,
    zone: str = "DE_LU",
    rule: IssueRule | None = None,
    target_metric: str = "actual_total_load",
    tso_metric: str = "tso_day_ahead_load_forecast",
    weights: dict[str, float] | None = None,
) -> pl.DataFrame:
    """Default target is load; renewables reuse the same machinery with another series
    (`target_metric`) and its TSO forecast (`tso_metric`)."""
    rule = rule or IssueRule()
    grid = target_grid(first, last, rule)
    load = _series(panel, zone, target_metric)
    tso = _series(panel, zone, tso_metric)
    load_local = _local_keys(load).group_by("local_date", "local_hour").agg(pl.col("value_mw").mean())

    g = grid.join(load.rename({"timestamp_utc": "valid_at_utc", "value_mw": "y"}), on="valid_at_utc", how="left")
    g = g.join(tso.rename({"timestamp_utc": "valid_at_utc", "value_mw": "tso_forecast"}), on="valid_at_utc",
               how="left")
    for k, name in [(7, "lag_d7"), (14, "lag_d14"), (2, "lag_d2")]:
        g = _lag_by_local(g, load_local, k, name)

    # Recent level: last 24 known hours before last_known_load_end (per delivery day).
    days = g.select("delivery_day", "last_known_load_end").unique().with_columns(
        w_hi=pl.col("last_known_load_end"),
        w_lo=pl.col("last_known_load_end") - pl.duration(hours=24),
        w7_hi=pl.col("last_known_load_end") - pl.duration(days=7),
        w7_lo=pl.col("last_known_load_end") - pl.duration(days=7, hours=24),
    )
    lt = load.rename({"timestamp_utc": "t"})
    rec = days.join_where(lt, pl.col("t") < pl.col("w_hi"), pl.col("t") >= pl.col("w_lo")).group_by(
        "delivery_day").agg(
        recent_24h_mean=pl.col("value_mw").mean(),
        last_known_load=pl.col("value_mw").sort_by("t").last(),
    )
    g = g.join(rec, on="delivery_day", how="left")
    # Same 24-h window one week earlier, to express the recent level as a weekly change.
    rec7 = days.join_where(lt, pl.col("t") < pl.col("w7_hi"), pl.col("t") >= pl.col("w7_lo")).group_by(
        "delivery_day").agg(recent_24h_mean_wk_ago=pl.col("value_mw").mean())
    g = g.join(rec7, on="delivery_day", how="left").with_columns(
        recent_level_ratio=pl.col("recent_24h_mean") / pl.col("recent_24h_mean_wk_ago")
    )

    cal = calendar.select(
        pl.col("date_local").alias("delivery_day"), "holiday_pop_share", "is_bridge_day", "is_christmas_period",
        "day_of_week", "day_of_year",
    )
    g = g.join(cal, on="delivery_day", how="left")
    cal_ref = calendar.select(
        (pl.col("date_local") + pl.duration(days=7)).alias("delivery_day"),
        pl.col("holiday_pop_share").alias("holiday_share_d7"),
    )
    g = g.join(cal_ref, on="delivery_day", how="left").with_columns(
        doy_sin=(2 * np.pi * pl.col("day_of_year") / 365.25).sin(),
        doy_cos=(2 * np.pi * pl.col("day_of_year") / 365.25).cos(),
        is_dst=((pl.col("local_hour") - pl.col("valid_at_utc").dt.hour()) % 24 == 2),
    )

    if "forecast_lead_hours" not in vintages.columns or vintages["forecast_lead_hours"].n_unique() != 1:
        raise ValueError("expected a fixed-lead weather archive (one forecast_lead_hours value)")
    g = weather_features_fixed_lead(vintages, g, weights)
    if analysis is not None:
        g = oracle_features(analysis, g)
    return g.sort("valid_at_utc")


FEATURES_CALENDAR = ["local_hour", "is_dst", "day_of_week", "doy_sin", "doy_cos", "holiday_pop_share", "is_bridge_day",
                     "is_christmas_period", "holiday_share_d7", "lead_hours"]
FEATURES_LAGS = ["lag_d7", "lag_d14", "lag_d2", "recent_24h_mean", "last_known_load", "recent_level_ratio"]
FEATURES_WEATHER = ["wx_t2m", "wx_ssrd", "wx_cloud", "wx_wind", "wx_t2m_day_mean", "wx_t2m_day_min",
                    "wx_t2m_day_max", "wx_ssrd_day_mean", "wx_hdd", "wx_cdd"]
# Temperature-only weather set: selected on the validation year (docs/reports/load_model_selection.md).
FEATURES_TEMP = ["wx_t2m", "wx_t2m_day_mean", "wx_t2m_day_min", "wx_t2m_day_max", "wx_hdd", "wx_cdd"]
FEATURES_TEMP_ORACLE = ["oracle_t2m", "oracle_t2m_day_mean", "oracle_t2m_day_min", "oracle_t2m_day_max",
                        "oracle_hdd", "oracle_cdd"]


def assert_point_in_time(df: pl.DataFrame, dataset: str = OM_DATASET) -> None:
    """Hard guard: every operational input must have existed by issue time."""
    lag_h = int(WEATHER_AVAILABILITY_LAG[dataset].total_seconds() // 3600)
    bad = df.filter(pl.col("weather_model_run") + pl.duration(hours=lag_h) > pl.col("issue_time_utc"))
    if bad.height:
        raise AssertionError(f"{bad.height} rows use weather runs not yet available at issue time")
    bad = df.filter(pl.col("last_known_load_end") > pl.col("issue_time_utc"))
    if bad.height:
        raise AssertionError("load availability cutoff after issue time")
    if (df["lead_hours"] <= 0).any():
        raise AssertionError("non-positive lead time")

