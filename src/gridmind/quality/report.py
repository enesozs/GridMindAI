"""Reproducible data-quality report over the processed tables (a pipeline check, not EDA)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from gridmind.config import PROCESSED_DIR

UTC = timezone.utc
CONTROL_AREAS = ["DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"]


def actuals_summary(panel: pl.DataFrame) -> list[dict]:
    s = (
        panel.group_by("zone_id", "metric")
        .agg(
            first=pl.col("timestamp_utc").min(),
            last=pl.col("timestamp_utc").max(),
            hours=pl.len(),
            missing_hours=pl.col("is_missing").sum(),
            partial_hours=(pl.col("is_partial_coverage") & (pl.col("n_present") > 0)).sum(),
            negative_hours=(pl.col("value_mw") < 0).sum(),
            mean_mw=pl.col("value_mw").mean().round(1),
        )
        .sort("zone_id", "metric")
    )
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()} for r in s.to_dicts()]


def dst_check(panel: pl.DataFrame, zone: str = "DE_LU", tz: str = "Europe/Berlin") -> dict:
    load = panel.filter((pl.col("zone_id") == zone) & (pl.col("metric") == "actual_total_load"))
    per_day = (
        load.with_columns(d=pl.col("timestamp_utc").dt.convert_time_zone(tz).dt.date())
        .group_by("d").agg(hours=pl.len()).sort("d")
    )
    inner = per_day.slice(1, max(per_day.height - 2, 0))  # drop possibly-truncated edge days
    h = inner["hours"]
    return {"local_days": inner.height, "days_23h": int((h == 23).sum()), "days_25h": int((h == 25).sum()),
            "days_other": int((~h.is_in([23, 24, 25])).sum())}


def control_area_consistency(panel: pl.DataFrame) -> dict:
    load = panel.filter(pl.col("metric") == "actual_total_load")
    areas = (
        load.filter(pl.col("zone_id").is_in(CONTROL_AREAS))
        .group_by("timestamp_utc")
        .agg(areas_mw=pl.col("value_mw").sum(), n=pl.col("value_mw").is_not_null().sum())
        .filter(pl.col("n") == 4)
    )
    de = load.filter(pl.col("zone_id") == "DE").select("timestamp_utc", de_mw="value_mw")
    j = areas.join(de, on="timestamp_utc").drop_nulls().with_columns(
        rel=(pl.col("areas_mw") - pl.col("de_mw")) / pl.col("de_mw")
    )
    if j.is_empty():
        return {"hours_compared": 0}
    return {
        "hours_compared": j.height,
        "median_rel_diff": round(float(j["rel"].median()), 5),
        "p99_abs_rel_diff": round(float(j["rel"].abs().quantile(0.99)), 5),
        "hours_over_1pct": int((j["rel"].abs() > 0.01).sum()),
    }


def identity_check(panel: pl.DataFrame, zone: str, lhs: str, rhs: dict[str, float]) -> dict:
    """Check lhs == sum(sign * rhs_metric) hour by hour, where all series exist.

    Differences are reported in MW and relative to the mean absolute level of `lhs`
    (per-hour percentages break down when a series is near zero, e.g. residual load).
    """
    z = panel.filter(pl.col("zone_id") == zone)
    wide = z.filter(pl.col("metric").is_in([lhs, *rhs])).pivot(
        on="metric", index="timestamp_utc", values="value_mw").drop_nulls()
    missing = [m for m in [lhs, *rhs] if m not in wide.columns]
    if missing or wide.is_empty():
        return {"hours_compared": 0, "missing_series": missing}
    implied = sum(pl.col(m) * sign for m, sign in rhs.items())
    d = wide.select(diff=pl.col(lhs) - implied, level=pl.col(lhs).abs())
    scale = float(d["level"].mean())
    ad = d["diff"].abs()
    return {
        "identity": f"{lhs} = " + " ".join(f"{'+' if v > 0 else '-'} {m}" for m, v in rhs.items()),
        "hours_compared": d.height,
        "median_abs_diff_mw": round(float(ad.median()), 1),
        "p99_abs_diff_mw": round(float(ad.quantile(0.99)), 1),
        "p99_rel_to_mean_level": round(float(ad.quantile(0.99)) / scale, 5),
        "hours_over_1pct_of_mean_level": int((ad > 0.01 * scale).sum()),
    }


IDENTITIES = {
    "residual_load_identity_DE_LU": ("DE_LU", "residual_load",
                                     {"actual_total_load": 1, "gen_wind_onshore": -1,
                                      "gen_wind_offshore": -1, "gen_solar": -1}),
    "tso_renewables_forecast_total_DE_LU": ("DE_LU", "tso_da_gen_wind_solar_total",
                                            {"tso_da_gen_solar": 1, "tso_da_gen_wind_onshore": 1,
                                             "tso_da_gen_wind_offshore": 1}),
}


def weather_summary(path: Path) -> dict:
    w = pl.read_parquet(path)
    skip = {"weather_model_run", "valid_at_utc", "forecast_lead_hours", "location", "weather_model"}
    vars_ = [c for c in w.columns if c not in skip and not c.endswith("_spread")]
    per_var = {}
    for v in vars_:
        ok = w.filter(pl.col(v).is_not_null() & ~pl.col(v).is_nan())
        per_var[v] = {
            "first_valid": ok["valid_at_utc"].min().isoformat() if ok.height else None,
            "null_share_after_first": round(float(
                w.filter(pl.col("valid_at_utc") >= ok["valid_at_utc"].min())[v].is_null().mean()), 4)
            if ok.height else None,
        }
    leads = w["forecast_lead_hours"].unique().to_list() if "forecast_lead_hours" in w.columns else []
    return {
        "rows": w.height,
        "locations": w["location"].n_unique(),
        "valid_from": w["valid_at_utc"].min().isoformat(),
        "valid_to": w["valid_at_utc"].max().isoformat(),
        "fixed_lead_hours": leads[0] if len(leads) == 1 else None,
        "variables": per_var,
    }


def build_report(processed_dir: Path = PROCESSED_DIR, out_dir: Path = Path("docs/evidence")) -> dict:
    panel = pl.read_parquet(processed_dir / "actuals_hourly.parquet")
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "actuals": actuals_summary(panel),
        "dst_check_DE_LU": dst_check(panel),
        "control_area_sum_vs_DE": control_area_consistency(panel),
        "identities": {k: identity_check(panel, *v) for k, v in IDENTITIES.items()},
        "weather": {},
    }
    for p in sorted(processed_dir.glob("weather_vintages_*.parquet")):
        report["weather"][p.stem.removeprefix("weather_vintages_")] = weather_summary(p)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "quality_report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


def to_markdown(report: dict) -> str:
    lines = ["# Data Quality Report", "", f"Generated {report['generated_at_utc']} by `gridmind quality-report`.", "",
             "## Actuals (hourly panel)", "",
             "| zone | metric | first | last | hours | missing | partial | negative | mean MW |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in report["actuals"]:
        lines.append(f"| {r['zone_id']} | {r['metric']} | {r['first'][:10]} | {r['last'][:10]} | {r['hours']} | "
                     f"{r['missing_hours']} | {r['partial_hours']} | {r['negative_hours']} | {r['mean_mw']} |")
    d = report["dst_check_DE_LU"]
    lines += ["", "## DST check (DE_LU actual load, local days)", "",
              f"23-hour days: {d['days_23h']} · 25-hour days: {d['days_25h']} · other lengths: {d['days_other']}", "",
              "## Control-area consistency", "", "Sum of the 4 TSO control areas vs national DE load:", "",
              "```json", json.dumps(report["control_area_sum_vs_DE"], indent=2), "```", "",
              "## Accounting identities", "",
              ("Published series that must add up. They replace an external cross-check: if SMARD's series were "
              "mis-mapped or mis-scaled, these would break."), "",
              "```json", json.dumps(report.get("identities", {}), indent=2), "```", "", "## Weather vintages", ""]
    for k, v in report["weather"].items():
        lines += [f"**{k}**", "", "```json", json.dumps(v, indent=2), "```", ""]
    return "\n".join(lines) + "\n"
