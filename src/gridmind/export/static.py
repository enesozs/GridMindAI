"""Export compact, versioned JSON artifacts for the static web app.

The frontend never computes science: every number it shows is produced here from the
validated pipeline outputs. Arrays are columnar (one list per field) to keep files
small. Missing values are JSON null, never 0.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from gridmind import __version__
from gridmind.config import PROCESSED_DIR, PROJECT_ROOT

UTC = timezone.utc
OUT = PROJECT_ROOT / "apps" / "web" / "public" / "data"
TZ = "Europe/Berlin"

CC_BY = "https://creativecommons.org/licenses/by/4.0/"
CHANGES = ("Transformed by GridMind: unit conversion (MWh per interval -> MW), hourly aggregation, "
           "population/area weighting of weather, and model forecasts derived from these inputs. "
           "No endorsement by the data providers is implied.")
ATTRIBUTION = [
    {"source": "Bundesnetzagentur | SMARD.de", "licence": "CC BY 4.0", "licence_url": CC_BY,
     "url": "https://www.smard.de",
     "used_for": "actual load, TSO day-ahead forecasts, generation (originally from ENTSO-E)"},
    {"source": "Weather data by Open-Meteo.com (NOAA GFS)", "licence": "CC BY 4.0 (free API, non-commercial)",
     "licence_url": CC_BY, "url": "https://open-meteo.com",
     "used_for": "GFS forecasts made 48 h before each hour (model inputs)"},
    {"source": "Natural Earth", "licence": "Public domain", "licence_url": "https://www.naturalearthdata.com/about/terms-of-use/",
     "url": "https://www.naturalearthdata.com", "used_for": "German federal state boundaries (approximate control-area footprints)"},
]


# Generation types folded to 6 display groups (stack order bottom -> top). The colour order
# for this stack was validated for CVD separation in light and dark mode.
GEN_GROUPS = {
    "wind": ["wind_onshore", "wind_offshore"],
    "solar": ["solar"],
    "other_renewables": ["biomass", "hydro", "other_renewable"],
    "gas": ["gas"],
    "coal": ["lignite", "hard_coal"],
    "other_and_storage": ["other_conventional", "pumped_storage", "nuclear"],
}


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, float):
        return round(v, 1)
    if isinstance(v, datetime):
        return v.isoformat().replace("+00:00", "Z")
    return v


def _cols(df: pl.DataFrame) -> dict:
    return {c: [_clean(v) for v in df[c].to_list()] for c in df.columns}


def _sanitize(o):
    """NaN/inf -> null recursively: browsers reject the bare NaN tokens Python's json emits."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    return o


def _write(name: str, payload: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payload = {"schema": name, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
               "code_version": __version__, "data_licences": "See meta.json: SMARD (CC BY 4.0), Open-Meteo "
               "(CC BY 4.0), Natural Earth (public domain). " + CHANGES, **payload}
    text = json.dumps(_sanitize(payload), separators=(",", ":"), default=str, allow_nan=False)
    (out / f"{name}.json").write_text(text)


def export_atlas(panel: pl.DataFrame, out: Path, days: int = 730) -> None:
    end = panel.filter(pl.col("metric") == "actual_total_load")["timestamp_utc"].max()
    start = end - timedelta(days=days)
    p = panel.filter(pl.col("timestamp_utc") >= start).with_columns(
        date=pl.col("timestamp_utc").dt.convert_time_zone(TZ).dt.date())

    # Daily mean load per region; a day with any missing hour is null (not partially averaged).
    # Anomaly = daily mean vs the same period one year earlier (mean of days 358..372 before,
    # i.e. +/-7 days around the same date last year; needs >= 10 valid days). Comparing with
    # the same season removes the dominant winter/summer cycle from the map colour.
    daily = (
        panel.filter(pl.col("metric") == "actual_total_load")
        .with_columns(date=pl.col("timestamp_utc").dt.convert_time_zone(TZ).dt.date())
        .group_by("zone_id", "date")
        .agg(mw=pl.col("value_mw").mean(), missing=pl.col("is_missing").sum())
        .with_columns(mw=pl.when(pl.col("missing") > 0).then(None).otherwise(pl.col("mw")))
        .sort("zone_id", "date")
    )
    lagged = []
    for k in range(358, 373):
        lagged.append(daily.select("zone_id", (pl.col("date") + pl.duration(days=k)).alias("date"),
                                   pl.col("mw").alias("mw_ref")))
    ref = (pl.concat(lagged).group_by("zone_id", "date")
           .agg(ref_mean=pl.col("mw_ref").mean(), ref_n=pl.col("mw_ref").is_not_null().sum()))
    daily = (
        daily.join(ref, on=["zone_id", "date"], how="left")
        .with_columns(anomaly=pl.when(pl.col("ref_n") >= 10).then(pl.col("mw") / pl.col("ref_mean") - 1))
        .filter(pl.col("date") >= start.astimezone(UTC).date())
    )
    regions = {}
    for (z,), g in daily.group_by("zone_id", maintain_order=True):
        regions[z] = {"date": [d.isoformat() for d in g["date"]], "load_mw": [_clean(v) for v in g["mw"].to_list()],
                      "anomaly": [None if v is None or math.isnan(v) else round(v, 4) for v in g["anomaly"].to_list()]}

    # Carpet (local day x local hour) for DE_LU, last 365 days. 25-h days keep the first hour-2.
    carpet = (
        p.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == "actual_total_load")
                 & (pl.col("timestamp_utc") >= end - timedelta(days=365)))
        .with_columns(hour=pl.col("timestamp_utc").dt.convert_time_zone(TZ).dt.hour())
        .group_by("date", "hour").agg(pl.col("value_mw").first()).sort("date", "hour")
    )
    dates = carpet["date"].unique().sort()
    grid = {d: [None] * 24 for d in dates.to_list()}
    for d, h, v in carpet.iter_rows():
        grid[d][h] = _clean(v)

    # Daily generation mix for DE-LU (mean MW per type), last 365 days.
    gen = (
        p.filter((pl.col("zone_id") == "DE_LU") & pl.col("metric").str.starts_with("gen_")
                 & (pl.col("timestamp_utc") >= end - timedelta(days=365)))
        .group_by("metric", "date").agg(mw=pl.col("value_mw").mean()).sort("date")
    )
    gen_dates = gen["date"].unique().sort().to_list()
    per_type = {}
    for (m,), g in gen.group_by("metric", maintain_order=True):
        per_type[m.removeprefix("gen_")] = dict(zip(g["date"].to_list(), g["mw"].to_list(), strict=True))
    mix = {}
    excluded = []
    for group, members in GEN_GROUPS.items():
        present = [m for m in members if m in per_type and any(v is not None for v in per_type[m].values())]
        excluded += [m for m in members if m not in present]
        vals = []
        for d in gen_dates:
            parts = [per_type[m].get(d) for m in present]
            vals.append(None if not parts or any(p is None for p in parts) else _clean(sum(parts)))
        mix[group] = vals

    _write("atlas", {
        "unit": "MW (mean power)",
        "data_end_utc": _clean(end),
        "regions": regions,
        "carpet": {"zone": "DE_LU", "dates": [d.isoformat() for d in grid], "hours": list(range(24)),
                   "load_mw": list(grid.values())},
        "generation_mix": {"zone": "DE_LU", "dates": [d.isoformat() for d in gen_dates], "series": mix,
                           "groups": GEN_GROUPS, "excluded_no_data_in_window": excluded},
        "attribution": ATTRIBUTION[:1] + ATTRIBUTION[2:],
    }, out)


def export_forecasts(preds: pl.DataFrame, out: Path, model: str = "gbm_weather") -> None:
    """Backtest forecasts for the replay scrubber (test period, hourly)."""
    g = preds.filter((pl.col("model") == model) & (pl.col("period") == "test")).sort("valid_at_utc")
    g = g.select("delivery_day", "issue_time_utc", "valid_at_utc", "y", "tso_forecast", "q05", "q25", "q50",
                 "q75", "q95")
    days = g["delivery_day"].unique().sort()
    # Per-day scores over hours where actual, TSO and median all exist.
    per_day = (
        g.filter(pl.col("y").is_not_null() & pl.col("tso_forecast").is_not_null() & pl.col("q50").is_not_null())
        .group_by("delivery_day")
        .agg(n=pl.len(), mae_gridmind=(pl.col("q50") - pl.col("y")).abs().mean(),
             mae_tso=(pl.col("tso_forecast") - pl.col("y")).abs().mean(),
             coverage_90=((pl.col("y") >= pl.col("q05")) & (pl.col("y") <= pl.col("q95"))).mean())
        .sort("delivery_day")
    )
    _write("forecast_replay", {
        "day_scores": {r["delivery_day"].isoformat(): {k: _clean(v) if k != "coverage_90" else round(v, 3)
                                                       for k, v in r.items() if k != "delivery_day"}
                       for r in per_day.to_dicts()},
        "model": model, "unit": "MW", "zone": "DE_LU", "period": "test (frozen holdout)",
        "issue_rule": "D-1 10:00 Europe/Berlin; weather = GFS forecast made 48 h before each hour",
        "days": [d.isoformat() for d in days],
        "hourly": _cols(g.with_columns(pl.col("delivery_day").cast(pl.String))),
    }, out)


def export_leaderboard(out: Path, report_dir: Path = PROJECT_ROOT / "docs" / "reports") -> None:
    lb = json.loads((report_dir / "load_leaderboard.json").read_text())
    _write("leaderboard", lb, out)


def export_track_record(out: Path, panel: pl.DataFrame) -> None:
    from gridmind.forecasting.live import read_track, score_track

    if read_track().is_empty():
        _write("track_record", {"status": "not_started", "days": [], "hourly": None}, out)
        return
    sc = score_track(panel).sort("valid_at_utc")
    days = (
        sc.group_by("delivery_day")
        .agg(
            issued_at_utc=pl.col("issued_at_utc").first(), on_time=pl.col("on_time").first(),
            weather_model_run=pl.col("weather_model_run").first(),
            hours=pl.len(), scored=(pl.col("y").is_not_null() & pl.col("tso_forecast").is_not_null()).sum(),
            mae_gridmind=((pl.col("q50") - pl.col("y")).abs()).filter(pl.col("tso_forecast").is_not_null()).mean(),
            mae_tso=((pl.col("tso_forecast") - pl.col("y")).abs()).filter(pl.col("q50").is_not_null()).mean(),
            coverage_90=((pl.col("y") >= pl.col("q05")) & (pl.col("y") <= pl.col("q95"))).filter(
                pl.col("y").is_not_null()).mean(),
        )
        .with_columns(complete=pl.col("scored") == pl.col("hours"))
        .sort("delivery_day")
    )
    done = days.filter(pl.col("complete") & pl.col("on_time"))
    summary = {
        "days_issued": days.height,
        "days_scored_on_time": done.height,
        "mae_gridmind": _clean(float(done["mae_gridmind"].mean())) if done.height else None,
        "mae_tso": _clean(float(done["mae_tso"].mean())) if done.height else None,
        "coverage_90": round(float(done["coverage_90"].mean()), 3) if done.height else None,
    }
    _write("track_record", {
        "status": "running", "unit": "MW", "summary": summary,
        "days": [{k: _clean(v.isoformat() if hasattr(v, "isoformat") and not isinstance(v, datetime) else v)
                  for k, v in r.items()} for r in days.to_dicts()],
        "hourly": _cols(sc.select("delivery_day", "valid_at_utc", "q05", "q50", "q95", "y", "tso_forecast")
                        .with_columns(pl.col("delivery_day").cast(pl.String))),
    }, out)


def export_renewables(out: Path) -> None:
    """Renewables: leaderboards per technology and test-year hourly replay (GridMind vs TSO)."""
    rep = PROJECT_ROOT / "docs" / "reports" / "renewables_results.json"
    preds_p = PROCESSED_DIR / "backtest_predictions_renewables.parquet"
    if not rep.exists() or not preds_p.exists():
        return
    lb = json.loads(rep.read_text())
    p = pl.read_parquet(preds_p).filter((pl.col("period") == "test") & (pl.col("model") == "gbm_weather"))
    replay = {}
    for (tgt,), g in p.group_by("target", maintain_order=True):
        g = g.sort("valid_at_utc").select("delivery_day", "valid_at_utc", "y", "tso_forecast", "q05", "q25",
                                          "q50", "q75", "q95")
        replay[tgt] = _cols(g.with_columns(pl.col("delivery_day").cast(pl.String)))
    _write("renewables", {
        "unit": "MW", "zone": "DE_LU",
        "note": "TSO renewables forecasts are published ~18:00 D-1, 8 h after GridMind's 10:00 issue time.",
        "results": lb, "replay": replay,
    }, out)


def export_storage(out: Path) -> None:
    """Storage Lab: summary, per-day reductions and hourly dispatch per forecast source."""
    rep = PROJECT_ROOT / "docs" / "reports" / "storage_results.json"
    per_day_p = PROCESSED_DIR / "storage_per_day.parquet"
    disp_p = PROCESSED_DIR / "storage_dispatch.parquet"
    if not (rep.exists() and per_day_p.exists() and disp_p.exists()):
        return
    res = json.loads(rep.read_text())
    per_day = pl.read_parquet(per_day_p).sort("delivery_day")
    disp = pl.read_parquet(disp_p).sort("valid_at_utc")
    sources = [r["source"] for r in res["summary"][1:]]
    hourly = {"valid_at_utc": None, "delivery_day": None, "residual": None}
    base = disp.filter(pl.col("source") == sources[0])
    hourly["valid_at_utc"] = [_clean(v) for v in base["valid_at_utc"].to_list()]
    hourly["delivery_day"] = [d.isoformat() for d in base["delivery_day"].to_list()]
    hourly["residual"] = [_clean(v) for v in base["residual"].to_list()]
    for s in sources:
        g = disp.filter(pl.col("source") == s)
        hourly[f"net_{s}"] = [_clean(v) for v in g["net_mw"].to_list()]
        hourly[f"after_{s}"] = [_clean(v) for v in (g["residual"] + g["net_mw"]).to_list()]
        hourly[f"soc_{s}"] = [_clean(v) for v in g["soc_mwh"].to_list()]
    _write("storage", {
        "unit": "MW / MWh", "fleet": res["fleet"], "period": res["period"], "summary": res["summary"],
        "per_day": _cols(per_day.select("delivery_day", "peak_before_mw", *[f"{s}_reduction_mw" for s in sources])
                         .with_columns(pl.col("delivery_day").cast(pl.String))),
        "hourly": hourly,
    }, out)


def export_control_areas(out: Path) -> None:
    """Control-area forecasts: results per series and the reconciled test-year hourly series."""
    rep = PROJECT_ROOT / "docs" / "reports" / "control_area_results.json"
    test_p = PROCESSED_DIR / "control_areas_test.parquet"
    if not (rep.exists() and test_p.exists()):
        return
    res = json.loads(rep.read_text())
    t = pl.read_parquet(test_p).sort("valid_at_utc")
    zones = ["DE", "DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"]
    chosen = res["chosen_method"]
    series = {}
    for z in zones:
        mae_rec = res["test"]["methods"][chosen]["mae_mw"][z]
        mae_tso = res["test"]["tso_mae_mw"][z]
        series[z] = {"mae_gridmind": mae_rec, "mae_tso": mae_tso, "skill_vs_tso": round(1 - mae_rec / mae_tso, 4),
                     "mae_base": res["test"]["methods"]["base"]["mae_mw"][z]}
    hourly = {"valid_at_utc": [_clean(v) for v in t["valid_at_utc"].to_list()],
              "delivery_day": [d.isoformat() for d in t["delivery_day"].to_list()]}
    for z in zones:
        hourly[f"y_{z}"] = [_clean(v) for v in t[f"y_{z}"].to_list()]
        hourly[f"tso_{z}"] = [_clean(v) for v in t[f"tso_{z}"].to_list()]
        hourly[f"gm_{z}"] = [_clean(v) for v in t[f"rec_{z}"].to_list()]
    _write("control_areas", {
        "unit": "MW", "chosen_method": chosen, "period": "test (frozen holdout)",
        "incoherence": {"base_mae_mw": res["test"]["base_incoherence_mae_mw"],
                        "tso_mae_mw": res["test"]["tso_incoherence_mae_mw"]},
        "methods": {m: v["mean_mae_mw"] for m, v in res["test"]["methods"].items()},
        "series": series, "hourly": hourly,
    }, out)


def export_all(out: Path = OUT) -> list[str]:
    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    export_atlas(panel, out)
    preds_p = PROCESSED_DIR / "backtest_predictions.parquet"
    if preds_p.exists():
        export_forecasts(pl.read_parquet(preds_p), out)
    if (PROJECT_ROOT / "docs" / "reports" / "load_leaderboard.json").exists():
        export_leaderboard(out)
    export_track_record(out, panel)
    export_renewables(out)
    export_storage(out)
    export_control_areas(out)
    _write("meta", {"attribution": ATTRIBUTION, "changes": CHANGES, "zone": "DE_LU", "timezone": TZ}, out)
    return sorted(p.name for p in out.glob("*.json"))
