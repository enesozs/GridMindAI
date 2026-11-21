"""Resolution handling.

Load and generation are POWER (MW) averaged over each interval, so the hourly value
is the MEAN of the sub-hourly values, never the sum. (Summing four 15-min MW values
gives a number 4x too large. Energy in MWh would be MW x hours.)

An hour is only valid if every sub-interval is present; otherwise it is null and
flagged, never silently averaged over the values that happen to exist.
"""

from __future__ import annotations

import polars as pl


def to_hourly_mean_mw(df: pl.DataFrame, value_col: str = "value") -> pl.DataFrame:
    """Aggregate an interval-start UTC series of MW to hourly means.

    Input columns: `timestamp_utc` (tz-aware UTC, interval start), `resolution_minutes`,
    `value_col`. Mixed resolutions are allowed (e.g. a 60 -> 15 min change mid-series).

    Output: `timestamp_utc` (hour start), `value_col` (MW mean or null), `n_expected`,
    `n_present`, `is_partial_coverage`.
    """
    if df.is_empty():
        return pl.DataFrame(
            schema={
                "timestamp_utc": pl.Datetime("us", "UTC"),
                value_col: pl.Float64,
                "n_expected": pl.Int64,
                "n_present": pl.Int64,
                "is_partial_coverage": pl.Boolean,
            }
        )
    bad = df.filter(60 % pl.col("resolution_minutes") != 0)
    if bad.height:
        raise ValueError("resolutions must divide 60 minutes")
    dupes = df.group_by("timestamp_utc").len().filter(pl.col("len") > 1)
    if dupes.height:
        raise ValueError(f"duplicate interval starts: {dupes.height}")

    return (
        df.with_columns(
            hour=pl.col("timestamp_utc").dt.truncate("1h"),
            expected=(60 // pl.col("resolution_minutes")),
        )
        .group_by("hour")
        .agg(
            mean=pl.col(value_col).mean(),
            n_present=pl.col(value_col).is_not_null().sum().cast(pl.Int64),
            n_expected=pl.col("expected").max().cast(pl.Int64),
        )
        .with_columns(
            is_partial_coverage=pl.col("n_present") < pl.col("n_expected"),
        )
        .with_columns(
            pl.when(pl.col("is_partial_coverage"))
            .then(None)
            .otherwise(pl.col("mean"))
            .alias(value_col)
        )
        .rename({"hour": "timestamp_utc"})
        .select("timestamp_utc", value_col, "n_expected", "n_present", "is_partial_coverage")
        .sort("timestamp_utc")
    )
