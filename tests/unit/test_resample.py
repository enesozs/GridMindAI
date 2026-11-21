from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from gridmind.quality.resample import to_hourly_mean_mw

UTC = timezone.utc


def _series(start, n, res_min, values):
    return pl.DataFrame(
        {
            "timestamp_utc": [start + timedelta(minutes=res_min * i) for i in range(n)],
            "resolution_minutes": [res_min] * n,
            "value": values,
        },
        schema={"timestamp_utc": pl.Datetime("us", "UTC"), "resolution_minutes": pl.Int64, "value": pl.Float64},
    )


def test_quarter_hours_are_averaged_not_summed():
    df = _series(datetime(2025, 1, 1, tzinfo=UTC), 8, 15, [40000, 42000, 44000, 46000, 50000, 50000, 50000, 50000])
    out = to_hourly_mean_mw(df)
    assert out["value"].to_list() == [43000.0, 50000.0]
    assert not out["is_partial_coverage"].any()


def test_incomplete_hour_is_null_and_flagged():
    df = _series(datetime(2025, 1, 1, tzinfo=UTC), 4, 15, [1.0, None, 3.0, 4.0])
    out = to_hourly_mean_mw(df)
    assert out["value"].to_list() == [None]
    assert out["n_present"].to_list() == [3]
    assert out["is_partial_coverage"].to_list() == [True]


def test_missing_row_entirely_is_detected_via_expected_count():
    df = _series(datetime(2025, 1, 1, tzinfo=UTC), 4, 15, [1.0, 2.0, 3.0, 4.0]).slice(0, 3)
    out = to_hourly_mean_mw(df)
    assert out["is_partial_coverage"].to_list() == [True]


def test_hourly_input_passes_through():
    df = _series(datetime(2025, 1, 1, tzinfo=UTC), 3, 60, [1.0, 2.0, 3.0])
    assert to_hourly_mean_mw(df)["value"].to_list() == [1.0, 2.0, 3.0]


def test_mixed_resolution_change():
    a = _series(datetime(2025, 1, 1, 0, tzinfo=UTC), 1, 60, [10.0])
    b = _series(datetime(2025, 1, 1, 1, tzinfo=UTC), 4, 15, [20.0, 20.0, 30.0, 30.0])
    out = to_hourly_mean_mw(pl.concat([a, b]))
    assert out["value"].to_list() == [10.0, 25.0]


def test_duplicates_rejected():
    df = _series(datetime(2025, 1, 1, tzinfo=UTC), 2, 15, [1.0, 2.0])
    with pytest.raises(ValueError):
        to_hourly_mean_mw(pl.concat([df, df]))


def test_fall_back_day_has_25_hours_of_quarter_hours():
    start = datetime(2025, 10, 25, 22, tzinfo=UTC)  # 00:00 CEST on 26 Oct
    df = _series(start, 100, 15, [1.0] * 100)
    out = to_hourly_mean_mw(df)
    assert out.height == 25
