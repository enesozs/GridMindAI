"""Build the validated hourly panel from interval-level actuals.

Every (zone, metric) series gets a complete hourly grid between its first and last
observed hour, so a missing hour is a visible row with `is_missing = true` rather than
an absent row (missing is not zero, and it is not invisible either).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from gridmind.config import PROCESSED_DIR


def hourly_panel(qh: pl.DataFrame) -> pl.DataFrame:
    keys = ["zone_id", "metric"]
    bad = qh.filter(60 % pl.col("resolution_minutes") != 0)
    if bad.height:
        raise ValueError("resolutions must divide 60 minutes")
    agg = (
        qh.with_columns(
            hour=pl.col("timestamp_utc").dt.truncate("1h"),
            expected=(60 // pl.col("resolution_minutes")),
        )
        .group_by(*keys, "hour")
        .agg(
            mean=pl.col("value_mw").mean(),
            n_present=pl.col("value_mw").is_not_null().sum().cast(pl.Int64),
            n_expected=pl.col("expected").max().cast(pl.Int64),
            source_created_utc=pl.col("source_created_utc").max(),
        )
        .with_columns(is_partial_coverage=pl.col("n_present") < pl.col("n_expected"))
        .with_columns(
            value_mw=pl.when(pl.col("is_partial_coverage")).then(None).otherwise(pl.col("mean"))
        )
        .rename({"hour": "timestamp_utc"})
        .drop("mean")
    )
    # Complete hourly grid per series between its first and last observed hour.
    bounds = agg.filter(pl.col("n_present") > 0).group_by(keys).agg(
        lo=pl.col("timestamp_utc").min(), hi=pl.col("timestamp_utc").max()
    )
    grid = bounds.with_columns(
        timestamp_utc=pl.datetime_ranges("lo", "hi", interval="1h", time_zone="UTC")
    ).explode("timestamp_utc").drop("lo", "hi")
    out = grid.join(agg, on=[*keys, "timestamp_utc"], how="left").with_columns(
        is_missing=pl.col("value_mw").is_null(),
        is_partial_coverage=pl.col("is_partial_coverage").fill_null(True),
        n_present=pl.col("n_present").fill_null(0),
    )
    return out.sort(*keys, "timestamp_utc")


def build(processed_dir: Path = PROCESSED_DIR) -> Path:
    qh = pl.read_parquet(processed_dir / "actuals_qh.parquet")
    panel = hourly_panel(qh)
    path = processed_dir / "actuals_hourly.parquet"
    panel.write_parquet(path)
    return path
