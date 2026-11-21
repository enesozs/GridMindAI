"""Day-ahead solar and wind generation forecasts for DE-LU.

Same issue-time contract as load (D-1 10:00 Europe/Berlin), same 48-h-lead weather
(Open-Meteo GFS), same backtest machinery. Differences:

- Weather enters per point (13 columns per variable), so the trees can learn which
  locations matter for each technology (PV in the south, wind in the north).
- Target = generation / capacity proxy, where the proxy is the maximum hourly output in
  the 30 days before the last known hour (known at issue time). This absorbs the fast
  growth of installed PV.
- Weather inputs (radiation, cloud, wind) exist only from 2024-01-20, so training starts
  in Feb 2024 and validation is the 6 months before the frozen test year.
- Benchmark: the TSOs' day-ahead generation forecasts from SMARD. They are published at
  about 18:00 D-1, 8 h after our issue time, so the comparison favours the TSOs.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from gridmind.features.build import FEATURES_CALENDAR, build_features
from gridmind.forecasting.backtest import ModelSpec
from gridmind.forecasting.models import NaiveModel, QuantileGBM

TARGETS = {
    "solar": ("gen_solar", "tso_da_gen_solar"),
    "wind_onshore": ("gen_wind_onshore", "tso_da_gen_wind_onshore"),
    "wind_offshore": ("gen_wind_offshore", "tso_da_gen_wind_offshore"),
}
TRAIN_START = date(2024, 2, 1)
VALIDATION = (date(2025, 5, 1), date(2025, 10, 31))
TEST = (date(2025, 11, 1), date(2026, 10, 31))
WEATHER_VARS = {
    "downward_short_wave_radiation_flux_surface": "ssrd",
    "total_cloud_cover_atmosphere": "cloud",
    "wind_speed_10m": "wind",
}


SITE_VARS = {
    "downward_short_wave_radiation_flux_surface": "ssrd",
    "total_cloud_cover_atmosphere": "cloud",
    "wind_speed_100m": "wind100",
    "temperature_2m": "t2m",
}


def point_weather(vintages: pl.DataFrame, variables: dict[str, str] | None = None, prefix: str = "pw"
                  ) -> pl.DataFrame:
    """Wide table: one column per (variable, location), keyed by valid hour."""
    variables = variables or WEATHER_VARS
    v = vintages.select("valid_at_utc", "location", *variables)
    wide = None
    for var, short in variables.items():
        w = v.pivot(on="location", index="valid_at_utc", values=var)
        w = w.rename({c: f"{prefix}_{short}_{c}" for c in w.columns if c != "valid_at_utc"})
        wide = w if wide is None else wide.join(w, on="valid_at_utc", how="full", coalesce=True)
    return wide


def build_renewables_features(panel, calendar, vintages, target: str, last: date, dataset: str,
                              site_vintages: pl.DataFrame | None = None) -> pl.DataFrame:
    metric, tso_metric = TARGETS[target]
    f = build_features(panel, calendar, vintages, TRAIN_START, last, dataset=dataset,
                       target_metric=metric, tso_metric=tso_metric)
    f = f.join(point_weather(vintages), on="valid_at_utc", how="left")
    if site_vintages is not None:  # v2: weather at solar/wind/offshore sites (100 m wind)
        f = f.join(point_weather(site_vintages, SITE_VARS, "sw"), on="valid_at_utc", how="left")
    # Capacity proxy: max hourly output in the 30 days before the last known hour (known at issue).
    s = panel.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == metric)).select(
        pl.col("timestamp_utc").alias("t"), "value_mw")
    days = f.select("delivery_day", "last_known_load_end").unique().with_columns(
        lo=pl.col("last_known_load_end") - pl.duration(days=30))
    cap = days.join_where(s, pl.col("t") < pl.col("last_known_load_end"), pl.col("t") >= pl.col("lo")).group_by(
        "delivery_day").agg(capacity_proxy=pl.col("value_mw").max())
    return f.join(cap, on="delivery_day", how="left")


def features_for(f: pl.DataFrame, version: str = "v1") -> list[str]:
    prefix = "pw_" if version == "v1" else "sw_"
    pw = [c for c in f.columns if c.startswith(prefix)]
    return FEATURES_CALENDAR + ["lag_d2", "lag_d7", "wx_t2m"] + pw


VARIANTS = {  # name -> (feature version, target base column); v1 = the original configuration
    "v1_population_points_ratio": ("v1", "capacity_proxy"),
    "v2_site_points_ratio": ("v2", "capacity_proxy"),
    "v2_site_points_absolute": ("v2", None),
}


def variant_spec(name: str, f: pl.DataFrame, as_name: str | None = None) -> ModelSpec:
    version, base = VARIANTS[name]
    feats = features_for(f, version)
    label = as_name or name
    return ModelSpec(label, lambda: QuantileGBM(label, feats, base_col=base))


def naive_specs() -> list[ModelSpec]:
    return [ModelSpec("naive_d2", lambda: NaiveModel("naive_d2", "lag_d2")),
            ModelSpec("naive_d7", lambda: NaiveModel("naive_d7", "lag_d7"))]


def model_specs(f: pl.DataFrame) -> list[ModelSpec]:
    feats = features_for(f)
    return [
        ModelSpec("naive_d2", lambda: NaiveModel("naive_d2", "lag_d2")),
        ModelSpec("naive_d7", lambda: NaiveModel("naive_d7", "lag_d7")),
        ModelSpec("gbm_weather", lambda: QuantileGBM("gbm_weather", feats, base_col="capacity_proxy")),
    ]


NAMES = {"solar": "Solar PV", "wind_onshore": "Wind onshore", "wind_offshore": "Wind offshore"}


def write_report(results: dict, path: Path) -> None:
    """Markdown benchmark from the results dict that `gridmind renewables` writes."""
    def row(period: dict, model: str) -> dict | None:
        return next((x for x in period["leaderboard"] if x["model"] == model), None)

    first = next(iter(results.values()))
    lines = [
        "# Day-ahead renewables forecasts (DE-LU): benchmark", "",
        "_Generated by `gridmind renewables` from `renewables_results.json`._", "",
        "**Setup.**",
        ("- Issue time D-1 10:00 Europe/Berlin, the same as the load forecast. Weather: GFS forecasts made 48 h "
         "before each hour (Open-Meteo)."),
        ("- **v1** used the 13 population points (radiation, cloud, 10 m wind). **v2** adds 16 points at solar, "
         "onshore-wind and offshore sites with 100 m wind, radiation, cloud and temperature."),
        ("- Model: quantile gradient boosting with conformal calibration. The target is either generation ÷ the "
         "maximum output of the previous 30 days (\"ratio\") or generation in MW (\"absolute\")."),
        ("- Per technology, the variant was chosen on the validation period by a rule fixed in advance (lowest "
         "mean pinball loss). **The test year had already been evaluated once for v1**, so v2's test result is "
         "a second look at the same year and is reported as such."),
        ("- Benchmark: the TSOs' day-ahead generation forecasts (SMARD). **They are published at about 18:00 "
         "the day before, 8 hours after GridMind's issue time**, with fresher weather and dedicated models."),
        "", (f"Validation {first['validation']['from']} → {first['validation']['to']}; test year "
            f"{first['test']['from']} → {first['test']['to']}."), "",
        "## Test-year MAE (MW)", "",
        "| Technology | Chosen variant | GridMind | GridMind v1 | TSO (18:00) | Skill vs TSO | 90% coverage |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, v in results.items():
        g, t, v1 = row(v["test"], "gbm_weather"), row(v["test"], "tso_official"), row(v["test"], "gbm_v1")
        v1_mae = f"{v1['mae_mw']:,.0f}" if v1 else "(same)"
        lines.append(f"| {NAMES[k]} | {v.get('chosen', 'v1')} | {g['mae_mw']:,.0f} | {v1_mae} | {t['mae_mw']:,.0f} "
                     f"| {g['skill_vs_tso']:+.0%} | {g['coverage_90']:.3f} |")
    if "selection" in first:
        lines += ["", "## Validation selection (mean pinball loss, MW; lower is better)", "",
                  "| Technology | " + " | ".join(VARIANTS) + " |", "|---|" + "---|" * len(VARIANTS)]
        for k, v in results.items():
            cells = [f"{v['selection'][m]['pinball_mean_mw']:,.0f}" + (" ✓" if m == v["chosen"] else "")
                     for m in VARIANTS]
            lines.append(f"| {NAMES[k]} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Reading the result", "",
        ("Weather at the right sites and height matters most for wind, where 10 m wind at population centres "
         "was a poor proxy. The remaining gap to the TSO forecasts comes from their later issue time, their "
         "dedicated models and their knowledge of installed capacity and curtailment. The intervals stay "
         "calibrated, so the model's uncertainty is honest even where its point forecasts are worse."), "",
        "Data: Bundesnetzagentur | SMARD.de (CC BY 4.0); weather data by Open-Meteo.com (NOAA GFS, CC BY 4.0).",
    ]
    path.write_text("\n".join(lines) + "\n")
