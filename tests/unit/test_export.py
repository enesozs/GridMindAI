"""SYNTHETIC panel tests for the static exporter's display rules."""

import json
from datetime import datetime, timedelta, timezone

import polars as pl

from gridmind.export.static import export_atlas

UTC = timezone.utc


def _panel(days: int = 400) -> pl.DataFrame:
    t0 = datetime(2025, 1, 1, 23, tzinfo=UTC)  # 00:00 Berlin, 2 Jan 2025
    ts = [t0 + timedelta(hours=h) for h in range(24 * days)]
    rows = []
    for metric, base in [("actual_total_load", 50_000.0), ("gen_solar", 5_000.0), ("gen_wind_onshore", 10_000.0)]:
        for i, t in enumerate(ts):
            # second year 10% higher load, so YoY anomaly should be about +10%
            v = base * (1.1 if i >= 24 * 365 else 1.0)
            rows.append(("DE_LU", metric, t, v, False))
    df = pl.DataFrame(rows, schema={"zone_id": pl.String, "metric": pl.String,
                                    "timestamp_utc": pl.Datetime("us", "UTC"), "value_mw": pl.Float64,
                                    "is_missing": pl.Boolean}, orient="row")
    # knock out one hour of load on a known day -> that whole day must export as null
    hole = datetime(2026, 1, 20, 11, tzinfo=UTC)
    return df.with_columns(
        value_mw=pl.when((pl.col("metric") == "actual_total_load") & (pl.col("timestamp_utc") == hole))
        .then(None).otherwise(pl.col("value_mw")),
        is_missing=(pl.col("metric") == "actual_total_load") & (pl.col("timestamp_utc") == hole),
    )


def test_atlas_export_rules(tmp_path):
    export_atlas(_panel(), tmp_path, days=60)
    d = json.loads((tmp_path / "atlas.json").read_text())
    r = d["regions"]["DE_LU"]
    i = r["date"].index("2026-01-20")
    assert r["load_mw"][i] is None and r["anomaly"][i] is None  # partial day is null, never a partial mean
    j = r["date"].index("2026-01-25")
    assert r["load_mw"][j] == 55_000.0
    assert abs(r["anomaly"][j] - 0.10) < 1e-6  # year-over-year vs same period last year
    mix = d["generation_mix"]
    assert set(mix["excluded_no_data_in_window"]) >= {"nuclear", "gas"}
    assert mix["series"]["solar"][0] == 5_000.0 and mix["series"]["wind"][0] == 10_000.0


def test_exported_json_never_contains_nan(tmp_path):
    from gridmind.export.static import _write

    _write("x", {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": float("nan")}}, tmp_path)
    text = (tmp_path / "x.json").read_text()
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["b"] == [1.0, None]
