"""Storage benchmark: how much peak-shaving value does each residual-load forecast capture?

For every day of the frozen test year, the fleet is scheduled on one residual-load
forecast and the schedule is applied to the realised residual load. Sources:

- perfect:            realised residual load (upper bound, not achievable)
- tso:                TSO load forecast - TSO solar/wind forecasts
- gridmind_load_tso_res: GridMind load forecast - TSO solar/wind forecasts
- gridmind:           GridMind load forecast - GridMind solar/wind forecasts
- naive_d7:           residual load at the same local hour one week earlier

Timing caveat: the TSO renewables forecasts are published around 18:00 D-1, later than
GridMind's 10:00 issue time; sources that use them are labelled accordingly.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

from gridmind.optimization.storage import DEFAULT_FLEET, Fleet, evaluate, plan

TZ = "Europe/Berlin"
SOURCES = {
    "perfect": "Perfect foresight (upper bound)",
    "tso": "TSO forecasts (load + renewables)",
    "gridmind_load_tso_res": "GridMind load + TSO renewables",
    "gridmind": "GridMind load + GridMind renewables",
    "naive_d7": "Naive: same hour last week",
}


def _metric(panel: pl.DataFrame, metric: str, name: str) -> pl.DataFrame:
    return panel.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == metric)).select(
        pl.col("timestamp_utc").alias("valid_at_utc"), pl.col("value_mw").alias(name))


def residual_sources(panel: pl.DataFrame, load_preds: pl.DataFrame, renew_preds: pl.DataFrame,
                     first: date, last: date) -> pl.DataFrame:
    """One row per valid hour with the realised residual and each forecast source (MW)."""
    base = load_preds.filter((pl.col("model") == "gbm_weather") & pl.col("delivery_day").is_between(first, last))
    df = base.select("delivery_day", "valid_at_utc", pl.col("q50").alias("load_gm"))
    for col, metric in [("residual", "residual_load"), ("load_tso", "tso_day_ahead_load_forecast"),
                        ("solar_tso", "tso_da_gen_solar"), ("on_tso", "tso_da_gen_wind_onshore"),
                        ("off_tso", "tso_da_gen_wind_offshore")]:
        df = df.join(_metric(panel, metric, col), on="valid_at_utc", how="left")
    rp = renew_preds.filter((pl.col("model") == "gbm_weather") & (pl.col("period") == "test"))
    for tgt, col in [("solar", "solar_gm"), ("wind_onshore", "on_gm"), ("wind_offshore", "off_gm")]:
        df = df.join(rp.filter(pl.col("target") == tgt).select("valid_at_utc", pl.col("q50").alias(col)),
                     on="valid_at_utc", how="left")
    # Naive: realised residual at the same LOCAL date-hour one week earlier.
    res = _metric(panel, "residual_load", "r").with_columns(
        d=pl.col("valid_at_utc").dt.convert_time_zone(TZ).dt.date(),
        h=pl.col("valid_at_utc").dt.convert_time_zone(TZ).dt.hour())
    naive = res.group_by("d", "h").agg(naive_d7=pl.col("r").mean()).with_columns(
        d=pl.col("d") + pl.duration(days=7))
    df = df.with_columns(d=pl.col("valid_at_utc").dt.convert_time_zone(TZ).dt.date(),
                         h=pl.col("valid_at_utc").dt.convert_time_zone(TZ).dt.hour()
                         ).join(naive, on=["d", "h"], how="left").drop("d", "h")
    renew_tso = pl.col("solar_tso") + pl.col("on_tso") + pl.col("off_tso")
    return df.with_columns(
        perfect=pl.col("residual"),
        tso=pl.col("load_tso") - renew_tso,
        gridmind_load_tso_res=pl.col("load_gm") - renew_tso,
        gridmind=pl.col("load_gm") - (pl.col("solar_gm") + pl.col("on_gm") + pl.col("off_gm")),
    ).sort("valid_at_utc")


def run(sources: pl.DataFrame, fleet: Fleet = DEFAULT_FLEET) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Plan and evaluate every complete day. Returns (per-day results, hourly dispatch)."""
    days, hourly = [], []
    for (d,), g in sources.group_by("delivery_day", maintain_order=True):
        g = g.sort("valid_at_utc")
        cols = ["residual", *SOURCES]
        if g.select(pl.any_horizontal(pl.col(cols).is_null().any())).item():
            continue  # incomplete day: skipped and counted, never filled
        actual = g["residual"].to_numpy()
        out = {"delivery_day": d, "hours": g.height}
        for s in SOURCES:
            sched = plan(g[s].to_numpy(), fleet)
            ev = evaluate(sched, actual)
            out[f"{s}_reduction_mw"] = ev["peak_reduction_mw"]
            out[f"{s}_throughput_mwh"] = ev["throughput_mwh"]
            out[f"{s}_status"] = ev["status"]
            out[f"{s}_forecast_mae_mw"] = float(np.abs(g[s].to_numpy() - actual).mean())
            hourly.append(pl.DataFrame({
                "delivery_day": [d] * g.height, "valid_at_utc": g["valid_at_utc"], "source": s,
                "net_mw": sched.net_mw, "soc_mwh": sched.soc_mwh[1:],
            }))
        out["peak_before_mw"] = float(actual.max())
        days.append(out)
    per_day = pl.DataFrame(days)
    disp = pl.concat(hourly).join(sources.select("valid_at_utc", "residual"), on="valid_at_utc", how="left")
    return per_day, disp


def summarise(per_day: pl.DataFrame, n_days_total: int) -> list[dict]:
    pf = float(per_day["perfect_reduction_mw"].mean())
    rows = []
    for s, label in SOURCES.items():
        red = per_day[f"{s}_reduction_mw"]
        rows.append({
            "source": s, "label": label,
            "mean_peak_reduction_mw": float(red.mean()),
            "value_captured": float(red.mean()) / pf if pf else None,
            "days_peak_worse": int((red < -1.0).sum()),
            "residual_forecast_mae_mw": float(per_day[f"{s}_forecast_mae_mw"].mean()),
            "mean_throughput_mwh": float(per_day[f"{s}_throughput_mwh"].mean()),
            "non_optimal_solves": int((per_day[f"{s}_status"] != "optimal").sum()),
        })
    return [{"days_evaluated": per_day.height, "days_skipped_incomplete": n_days_total - per_day.height}, *rows]


def write_report(summary: list[dict], fleet: Fleet, period: tuple[date, date], path) -> None:
    meta, rows = summary[0], summary[1:]
    lines = [
        "# Storage dispatch on residual load: benchmark", "",
        "_Generated by `gridmind storage`._", "",
        (f"A stylised storage fleet ({fleet.power_mw / 1000:.0f} GW / {fleet.energy_mwh / 1000:.0f} GWh, "
         f"{fleet.round_trip_eff:.0%} round-trip efficiency, state of charge "
         f"{fleet.soc_min_frac:.0%}–{fleet.soc_max_frac:.0%}, starting and ending each day at "
         f"{fleet.soc_start_frac:.0%}) is scheduled day-ahead to minimise the daily peak of residual load "
         "(load − wind − solar). Each schedule is planned on a forecast and then applied to the realised "
         "residual load. Value is measured as peak reduction, not revenue: this project uses no price data."),
        "",
        (f"Test year {period[0]} → {period[1]}: {meta['days_evaluated']} days evaluated, "
         f"{meta['days_skipped_incomplete']} skipped because a forecast or the actual was incomplete."), "",
        ("| Forecast used for planning | Mean peak reduction | Share of perfect-foresight value "
        "| Days the peak got worse | Residual forecast MAE | Mean throughput |"),
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        vc = "—" if r["value_captured"] is None else f"{r['value_captured']:.0%}"
        lines.append(f"| {r['label']} | {r['mean_peak_reduction_mw']:,.0f} MW | {vc} | {r['days_peak_worse']} "
                     f"| {r['residual_forecast_mae_mw']:,.0f} MW | {r['mean_throughput_mwh']:,.0f} MWh |")
    lines += [
        "",
        ("Notes. The TSO renewables forecasts are published around 18:00 the day before, later than GridMind's "
         "10:00 issue time, so sources that use them had more recent information. All solves are reported; "
         "a non-optimal solve would appear in the results JSON."), "",
        "Data: Bundesnetzagentur | SMARD.de (CC BY 4.0); weather data by Open-Meteo.com (CC BY 4.0).",
    ]
    path.write_text("\n".join(lines) + "\n")
