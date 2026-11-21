"""GridMind command-line entry point (`uv run gridmind --help`)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import polars as pl
import typer

from gridmind.config import INTERIM_DIR

app = typer.Typer(no_args_is_help=True, add_completion=False)
UTC = timezone.utc


@app.command("smard-sample")
def smard_sample(start: str = "2025-03-24", days: int = 14, region: str = "DE-LU") -> None:
    """Verify SMARD filter ids and pull a short sample of actual load + TSO forecast."""
    from pathlib import Path

    from gridmind.providers import smard
    from gridmind.quality.resample import to_hourly_mean_mw
    from gridmind.timeutils import delivery_day_bounds_utc

    c = smard.client()
    report: dict = {"filters": {}, "sample": {}}
    for metric in smard.FILTERS:
        try:
            idx = smard.week_index(c, metric, region)
            report["filters"][metric] = {
                "filter_id": smard.FILTERS[metric],
                "first_week": datetime.fromtimestamp(idx[0] / 1000, UTC).isoformat(),
                "last_week": datetime.fromtimestamp(idx[-1] / 1000, UTC).isoformat(),
                "n_weeks": len(idx),
            }
        except FileNotFoundError:
            report["filters"][metric] = {"filter_id": smard.FILTERS[metric], "error": "404 for region"}

    d0 = date.fromisoformat(start)
    s, _ = delivery_day_bounds_utc(d0, "Europe/Berlin")
    _, e = delivery_day_bounds_utc(d0 + timedelta(days=days - 1), "Europe/Berlin")
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    for metric in ["actual_total_load", "tso_day_ahead_load_forecast"]:
        idx = smard.week_index(c, metric, region)
        weeks = [w for w in idx if s.timestamp() * 1000 - 7 * 86400_000 < w < e.timestamp() * 1000]
        parts = [smard.fetch_week(c, metric, region, w) for w in weeks]
        rows = pl.concat([p.rows for p in parts]).filter(
            (pl.col("timestamp_utc") >= s) & (pl.col("timestamp_utc") < e)
        )
        rows.write_parquet(INTERIM_DIR / f"smard_sample_{metric}_{region}.parquet")
        hourly = to_hourly_mean_mw(
            rows.select("timestamp_utc", "resolution_minutes", pl.col("value_mw").alias("value"))
        )
        report["sample"][metric] = {
            "raw_sha256": [p.record.sha256 for p in parts],
            "source_created_utc": [p.created_utc.isoformat() if p.created_utc else None for p in parts],
            "n_quarter_hours": rows.height,
            "expected_quarter_hours": int((e - s).total_seconds() // 900),
            "n_null": int(rows["value_mw"].null_count()),
            "hourly_rows": hourly.height,
            "hourly_partial": int(hourly["is_partial_coverage"].sum()),
            "mean_mw": round(float(rows["value_mw"].mean()), 1),
        }
    Path("docs/evidence").mkdir(parents=True, exist_ok=True)
    Path("docs/evidence/smard_sample_summary.json").write_text(json.dumps(report, indent=2))
    typer.echo(json.dumps(report, indent=2))


@app.command("ingest-smard")
def ingest_smard_cmd(start: str = "2020-10-01", refresh_weeks: int = 6) -> None:
    """Incrementally ingest SMARD actuals for all planned regions/metrics."""
    from gridmind.ingest.smard_ingest import ingest, write_actuals

    s = datetime.fromisoformat(start).replace(tzinfo=UTC)
    df = ingest(s, refresh_weeks=refresh_weeks, log=typer.echo)
    path = write_actuals(df)
    typer.echo(f"wrote {path} ({df.height} rows)")


@app.command("ingest-openmeteo")
def ingest_openmeteo_cmd(start_t2m: str = "2021-05-01", start_other: str = "2024-01-01",
                         end: str | None = None, oracle: bool = True) -> None:
    """Fixed-48h-lead GFS forecasts (Open-Meteo Previous Runs) + lead-0 'oracle' values."""
    from gridmind.config import PROCESSED_DIR
    from gridmind.providers import openmeteo as om
    from gridmind.providers.weather import DE_LU_POINTS

    e = date.fromisoformat(end) if end else datetime.now(UTC).date() + timedelta(days=2)
    df = om.fetch_all(date.fromisoformat(start_t2m), date.fromisoformat(start_other), e, log=typer.echo)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / f"weather_vintages_{om.DATASET}.parquet"
    if path.exists():  # incremental: archived fixed-lead values are immutable; new rows win on overlap
        old = pl.read_parquet(path)
        df = pl.concat([old.join(df.select("location", "valid_at_utc"), on=["location", "valid_at_utc"],
                                 how="anti"), df], how="vertical_relaxed").sort("location", "valid_at_utc")
    df.write_parquet(path)
    typer.echo(f"vintages: {df.height} rows; null t2m {df['temperature_2m'].null_count()}")

    if not oracle:
        return
    # Oracle (hindsight): lead-0 values, i.e. the newest run's first hours (close to an analysis).
    # Labelled and stored separately; NEVER an operational feature.
    import httpx

    frames = []
    with httpx.Client(headers={"User-Agent": "GridMindAI research pipeline (non-commercial)"}) as c:
        for p in DE_LU_POINTS:
            content = om._get(c, {"latitude": p.lat, "longitude": p.lon,
                                  "hourly": "temperature_2m,shortwave_radiation", "models": om.MODEL,
                                  "start_date": start_t2m, "end_date": e.isoformat(), "timezone": "GMT",
                                  "past_days": 0})
            h = json.loads(content)["hourly"]
            frames.append(pl.DataFrame({"valid_at_utc": h["time"], "temperature_2m": h["temperature_2m"],
                                        "downward_short_wave_radiation_flux_surface": h["shortwave_radiation"]},
                                       schema_overrides={"temperature_2m": pl.Float64,
                                                         "downward_short_wave_radiation_flux_surface": pl.Float64})
                          .with_columns(location=pl.lit(p.location_id)))
    ana = pl.concat(frames).with_columns(
        pl.col("valid_at_utc").str.to_datetime("%Y-%m-%dT%H:%M").dt.replace_time_zone("UTC"),
        label=pl.lit("lead0_hindsight"))
    ana.write_parquet(PROCESSED_DIR / "weather_analysis_openmeteo-lead0.parquet")
    typer.echo(f"oracle: {ana.height} rows; null t2m {ana['temperature_2m'].null_count()}")


@app.command("ingest-renewables-weather")
def ingest_renewables_weather_cmd(start: str = "2024-01-01", end: str | None = None) -> None:
    """48-h-lead weather at solar, wind and offshore sites (radiation, cloud, 100 m wind, temperature)."""
    from gridmind.config import PROCESSED_DIR
    from gridmind.providers import openmeteo as om

    e = date.fromisoformat(end) if end else datetime.now(UTC).date() + timedelta(days=2)
    df = om.fetch_renewables_points(date.fromisoformat(start), e, log=typer.echo)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(PROCESSED_DIR / "weather_vintages_renewables_points.parquet")
    nn = {c: df.filter(pl.col(c).is_not_null())["valid_at_utc"].min() for c in
          ["downward_short_wave_radiation_flux_surface", "wind_speed_100m", "temperature_2m"]}
    typer.echo(f"rows {df.height}; first non-null per variable: {nn}")


@app.command("build-panel")
def build_panel_cmd() -> None:
    """Build the hourly panel and the calendar table from processed actuals."""
    from gridmind.config import PROCESSED_DIR
    from gridmind.features.calendar import calendar_table
    from gridmind.panel import build

    typer.echo(f"wrote {build()}")
    cal = calendar_table(date(2020, 1, 1), date(datetime.now(UTC).year + 1, 12, 31))
    cal.write_parquet(PROCESSED_DIR / "calendar_de.parquet")
    typer.echo(f"wrote calendar ({cal.height} days)")


@app.command("quality-report")
def quality_report_cmd() -> None:
    """Write docs/evidence/quality_report.json and docs/QUALITY_REPORT.md."""
    from pathlib import Path

    from gridmind.quality.report import build_report, to_markdown

    rep = build_report()
    Path("docs/QUALITY_REPORT.md").write_text(to_markdown(rep))
    typer.echo(json.dumps({k: rep[k] for k in ("dst_check_DE_LU", "control_area_sum_vs_DE", "weather")}, indent=2,
                          default=str))


@app.command("build-features")
def build_features_cmd(first: str = "2021-05-03", last: str | None = None) -> None:
    """Build the point-in-time feature matrix for DE-LU (with oracle columns if available)."""
    from gridmind.config import PROCESSED_DIR
    from gridmind.features.build import assert_point_in_time, build_features

    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    cal = pl.read_parquet(PROCESSED_DIR / "calendar_de.parquet")
    from gridmind.providers.openmeteo import DATASET

    vint = pl.read_parquet(PROCESSED_DIR / f"weather_vintages_{DATASET}.parquet")
    ana_p = PROCESSED_DIR / "weather_analysis_openmeteo-lead0.parquet"
    ana = pl.read_parquet(ana_p) if ana_p.exists() else None
    ld = date.fromisoformat(last) if last else datetime.now(UTC).date() + timedelta(days=1)
    feat = build_features(panel, cal, vint, date.fromisoformat(first), ld, dataset=DATASET, analysis=ana)
    assert_point_in_time(feat.drop_nulls("weather_model_run"), DATASET)
    path = PROCESSED_DIR / "features_DE_LU.parquet"
    feat.write_parquet(path)
    typer.echo(f"wrote {path}: {feat.height} rows, {len(feat.columns)} columns; "
               f"null y: {feat['y'].null_count()}, null wx_t2m: {feat['wx_t2m'].null_count()}")


@app.command("select-model")
def select_model_cmd() -> None:
    """Compare GBM target variants on the VALIDATION year only; writes load_model_selection.md."""
    from pathlib import Path

    from gridmind.config import PROCESSED_DIR
    from gridmind.features.build import FEATURES_CALENDAR, FEATURES_LAGS, FEATURES_WEATHER
    from gridmind.forecasting import backtest as bt
    from gridmind.forecasting import report as rp
    from gridmind.forecasting.models import QuantileGBM

    feat = pl.read_parquet(PROCESSED_DIR / "features_DE_LU.parquet")
    feats = FEATURES_CALENDAR + FEATURES_LAGS + FEATURES_WEATHER
    temp_only = FEATURES_CALENDAR + FEATURES_LAGS + ["wx_t2m", "wx_t2m_day_mean", "wx_t2m_day_min",
                                                     "wx_t2m_day_max", "wx_hdd", "wx_cdd"]
    variants = [
        bt.ModelSpec("gbm_absolute", lambda: QuantileGBM("gbm_absolute", feats, base_col=None)),
        bt.ModelSpec("gbm_ratio_recent24h", lambda: QuantileGBM("gbm_ratio_recent24h", feats,
                                                                base_col="recent_24h_mean")),
        bt.ModelSpec("gbm_ratio_lag_d7", lambda: QuantileGBM("gbm_ratio_lag_d7", feats, base_col="lag_d7")),
        bt.ModelSpec("gbm_ratio_recent24h_temp_only", lambda: QuantileGBM(
            "gbm_ratio_recent24h_temp_only", temp_only, base_col="recent_24h_mean")),
    ]
    p = bt.run_backtest(feat, bt.VALIDATION, variants, log=typer.echo)
    lb = rp.leaderboard(rp.scored_rows(p))
    typer.echo(lb.select("model", "mae_mw", "rmse_mw", "pinball_mean_mw", "coverage_90"))
    md = ["# Load model selection (validation year only)", "",
          f"Validation period {bt.VALIDATION[0]} → {bt.VALIDATION[1]}. The test year was not used.", "",
          "Variants differ only in the GBM target: absolute MW, or the ratio to a level known at issue time.", "",
          rp._md_table(lb, ["model", "mae_mw", "rmse_mw", "bias_mw", "pinball_mean_mw", "coverage_90",
                             "skill_vs_tso"], {"mae_mw": ",.0f", "rmse_mw": ",.0f", "bias_mw": "+,.0f",
                                               "pinball_mean_mw": ",.0f", "coverage_90": ".3f",
                                               "skill_vs_tso": "+.1%"}),
          "Selection rule (fixed before running): lowest mean pinball loss; ties broken by MAE."]
    Path("docs/reports").mkdir(parents=True, exist_ok=True)
    Path("docs/reports/load_model_selection.md").write_text("\n".join(md) + "\n")


@app.command("backtest")
def backtest_cmd(periods: str = "validation,test") -> None:
    """Rolling-origin backtest + benchmark report (docs/reports/load_benchmark.md)."""
    from pathlib import Path

    from gridmind.config import PROCESSED_DIR
    from gridmind.forecasting import backtest as bt
    from gridmind.forecasting import report as rp

    feat = pl.read_parquet(PROCESSED_DIR / "features_DE_LU.parquet")
    has_oracle = "oracle_t2m" in feat.columns and feat["oracle_t2m"].null_count() < feat.height
    specs = bt.model_specs(include_oracle=has_oracle)
    results, preds = {}, []
    for name in periods.split(","):
        period = bt.VALIDATION if name == "validation" else bt.TEST
        typer.echo(f"{name}: {period[0]} → {period[1]}")
        p = bt.run_backtest(feat, period, specs, log=typer.echo).with_columns(period=pl.lit(name))
        preds.append(p)
        s = rp.scored_rows(p)
        ops = [m for m in ["gbm_weather", "gbm_no_weather", "naive_d7", "ridge_calendar_lags"]
               if m in s["model"].unique()]
        bd = rp.breakdowns(s, ops + (["gbm_oracle_weather"] if has_oracle else []))
        pairs = [("gbm_weather", None), ("gbm_weather", "gbm_no_weather"), ("gbm_weather", "naive_d7"),
                 ("gbm_no_weather", None)]
        results[name] = {
            "manifest": bt.run_manifest(name, period, feat, specs),
            "n_hours": s["valid_at_utc"].n_unique(),
            "leaderboard": rp.leaderboard(s),
            "dm": rp.dm_tests(s, pairs),
            "breakdowns": bd,
            "figures": rp.figures(s, bd, Path("docs/reports/figures"), name),
        }
        typer.echo(results[name]["leaderboard"].select("model", "mae_mw", "skill_vs_tso", "coverage_90"))
    allp = pl.concat(preds)
    allp.write_parquet(PROCESSED_DIR / "backtest_predictions.parquet")
    rp.write_report(results, Path("docs/reports/load_benchmark.md"))
    typer.echo("wrote docs/reports/load_benchmark.md")


@app.command("export")
def export_cmd() -> None:
    """Write the JSON artifacts the static web app reads (apps/web/public/data)."""
    from gridmind.export.static import export_all

    typer.echo(f"exported: {', '.join(export_all())}")


@app.command("live")
def live_cmd(delivery_day: str | None = None, skip_ingest: bool = False) -> None:
    """Issue the live forecast for tomorrow (or a given day) and append it to the track record."""
    from gridmind.export.static import OUT, export_track_record
    from gridmind.forecasting.live import issue_live

    now = datetime.now(UTC)
    d = date.fromisoformat(delivery_day) if delivery_day else (pd.Timestamp(now).tz_convert("Europe/Berlin")
                                                                 .date() + timedelta(days=1))
    if not skip_ingest:
        recent = (now - timedelta(days=10)).date().isoformat()
        ingest_smard_cmd(start=(now - timedelta(days=60)).date().isoformat(), refresh_weeks=3)
        ingest_openmeteo_cmd(start_t2m=recent, start_other=recent, oracle=False)
        build_panel_cmd()
    out = issue_live(d, now=now)
    on_time = bool(out["on_time"][0])
    typer.echo(f"issued {d}: {out.height} hours, weather run {out['weather_model_run'][0]}, on_time={on_time}")
    from gridmind.config import PROCESSED_DIR

    export_track_record(OUT, pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet"))


@app.command("renewables")
def renewables_cmd() -> None:
    """Solar/wind forecasts vs TSO: variant chosen on validation (pinball), test evaluated once."""
    from pathlib import Path

    from gridmind.config import PROCESSED_DIR
    from gridmind.forecasting import backtest as bt
    from gridmind.forecasting import renewables as rn
    from gridmind.forecasting import report as rp
    from gridmind.providers.openmeteo import DATASET

    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    cal = pl.read_parquet(PROCESSED_DIR / "calendar_de.parquet")
    vint = pl.read_parquet(PROCESSED_DIR / f"weather_vintages_{DATASET}.parquet")
    sites = pl.read_parquet(PROCESSED_DIR / "weather_vintages_renewables_points.parquet")
    last = datetime.now(UTC).date() + timedelta(days=1)
    out, preds = {}, []

    def board(p: pl.DataFrame) -> dict:
        s = rp.scored_rows(p)
        return {"n_hours": s["valid_at_utc"].n_unique(), "leaderboard": rp.leaderboard(s).to_dicts(),
                "dm": rp.dm_tests(s, [("gbm_weather", None)])}

    for tgt in rn.TARGETS:
        f = rn.build_renewables_features(panel, cal, vint, tgt, last, DATASET, site_vintages=sites)
        f.write_parquet(PROCESSED_DIR / f"features_renew_{tgt}.parquet")
        typer.echo(f"{tgt}: validation selection")
        val = bt.run_backtest(f, rn.VALIDATION, rn.naive_specs() + [rn.variant_spec(v, f) for v in rn.VARIANTS],
                              log=typer.echo)
        sel = {r["model"]: {"pinball_mean_mw": r["pinball_mean_mw"], "mae_mw": r["mae_mw"]}
               for r in rp.leaderboard(rp.scored_rows(val)).to_dicts() if r["model"] in rn.VARIANTS}
        chosen = min(sel, key=lambda m: sel[m]["pinball_mean_mw"])  # pre-registered rule
        # v1 first so that, when v1 itself is chosen, the "gbm_weather" name wins (dict keys collide).
        keep = {"v1_population_points_ratio": "gbm_v1", chosen: "gbm_weather"}
        val_ship = val.filter(pl.col("model").is_in(["naive_d2", "naive_d7", *keep])).with_columns(
            model=pl.col("model").replace(keep))
        typer.echo(f"{tgt}: chosen {chosen}; test")
        specs = rn.naive_specs() + [rn.variant_spec(chosen, f, "gbm_weather")]
        if chosen != "v1_population_points_ratio":
            specs.append(rn.variant_spec("v1_population_points_ratio", f, "gbm_v1"))
        test = bt.run_backtest(f, rn.TEST, specs, log=typer.echo)
        for name, p, period in [("validation", val_ship, rn.VALIDATION), ("test", test, rn.TEST)]:
            preds.append(p.with_columns(period=pl.lit(name), target=pl.lit(tgt)))
            out.setdefault(tgt, {})[name] = {"from": str(period[0]), "to": str(period[1]), **board(p)}
        out[tgt]["selection"] = sel
        out[tgt]["chosen"] = chosen
    pl.concat(preds, how="diagonal_relaxed").write_parquet(PROCESSED_DIR / "backtest_predictions_renewables.parquet")
    Path("docs/reports/renewables_results.json").write_text(json.dumps(out, indent=2, default=str))
    rn.write_report(out, Path("docs/reports/renewables_benchmark.md"))
    for tgt, r in out.items():
        lb = {x["model"]: x["mae_mw"] for x in r["test"]["leaderboard"]}
        typer.echo(f"{tgt}: chosen {r['chosen']}  test MAE gm {lb.get('gbm_weather'):.0f}  v1 {lb.get('gbm_v1', float('nan')):.0f}"
                   f"  tso {lb['tso_official']:.0f}")


@app.command("storage")
def storage_cmd() -> None:
    """Storage dispatch benchmark on residual load over the frozen test year."""
    from pathlib import Path

    from gridmind.config import PROCESSED_DIR
    from gridmind.forecasting.backtest import TEST
    from gridmind.optimization import benchmark as sb
    from gridmind.optimization.storage import Fleet

    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    load_p = pl.read_parquet(PROCESSED_DIR / "backtest_predictions.parquet").filter(pl.col("period") == "test")
    renew_p = pl.read_parquet(PROCESSED_DIR / "backtest_predictions_renewables.parquet")
    src = sb.residual_sources(panel, load_p, renew_p, *TEST)
    fleet = Fleet()
    per_day, disp = sb.run(src, fleet)
    per_day.write_parquet(PROCESSED_DIR / "storage_per_day.parquet")
    disp.write_parquet(PROCESSED_DIR / "storage_dispatch.parquet")
    summary = sb.summarise(per_day, src["delivery_day"].n_unique())
    Path("docs/reports/storage_results.json").write_text(json.dumps(
        {"fleet": fleet.__dict__, "period": [str(TEST[0]), str(TEST[1])], "summary": summary}, indent=2))
    sb.write_report(summary, fleet, TEST, Path("docs/reports/storage_benchmark.md"))
    for r in summary[1:]:
        typer.echo(f"{r['source']:24s} reduction {r['mean_peak_reduction_mw']:8.0f} MW  "
                   f"captured {r['value_captured']:.0%}  worse days {r['days_peak_worse']}")
    typer.echo(f"days evaluated {summary[0]}")


@app.command("control-areas")
def control_areas_cmd() -> None:
    """Per-area + national load backtests, then hierarchical reconciliation (report + JSON)."""
    from pathlib import Path

    from gridmind.config import PROCESSED_DIR
    from gridmind.forecasting import backtest as bt
    from gridmind.forecasting import control_areas as ca
    from gridmind.providers.openmeteo import DATASET

    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    cal = pl.read_parquet(PROCESSED_DIR / "calendar_de.parquet")
    vint = pl.read_parquet(PROCESSED_DIR / f"weather_vintages_{DATASET}.parquet")
    last = bt.TEST[1]
    preds = []
    for z in ca.ZONES:
        f = ca.build_zone_features(panel, cal, vint, z, date(2021, 5, 3), last)
        for name, period in [("validation", bt.VALIDATION), ("test", bt.TEST)]:
            typer.echo(f"{z} {name}")
            p = bt.run_backtest(f, period, [ca.model_spec()], log=typer.echo)
            preds.append(p.with_columns(zone=pl.lit(z), period=pl.lit(name)))
    allp = pl.concat(preds)
    allp.write_parquet(PROCESSED_DIR / "backtest_predictions_areas.parquet")
    wide = ca.wide_point_forecasts(allp)
    res, chosen, final = ca.select_and_test(wide)
    test = wide.filter(pl.col("period") == "test")
    rec = test.select("valid_at_utc", "delivery_day").with_columns(
        **{f"rec_{z}": pl.Series(final[:, i]) for i, z in enumerate(ca.ZONES)})
    test.join(rec, on=["valid_at_utc", "delivery_day"]).write_parquet(PROCESSED_DIR / "control_areas_test.parquet")
    Path("docs/reports/control_area_results.json").write_text(json.dumps(res, indent=2))
    ca.write_report(res, Path("docs/reports/control_area_benchmark.md"))
    typer.echo(f"chosen: {chosen}")
    for m in ca.METHODS:
        typer.echo(f"  {m:12s} test mean MAE {res['test']['methods'][m]['mean_mae_mw']:8.0f} MW")
    typer.echo(f"  TSO MAE per zone: {res['test']['tso_mae_mw']}")


@app.command("status")
def status_cmd(max_load_age_h: int = 6, strict: bool = True) -> None:
    """Data-freshness and pipeline health checks; exits 1 if anything is stale (for schedulers)."""
    from gridmind.config import PROCESSED_DIR
    from gridmind.forecasting.live import read_track
    from gridmind.providers.openmeteo import DATASET

    now = datetime.now(UTC)
    checks: list[tuple[str, bool, str]] = []
    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    last_load = panel.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == "actual_total_load")
                             & pl.col("value_mw").is_not_null())["timestamp_utc"].max()
    age = (now - last_load).total_seconds() / 3600
    checks.append(("actual load fresh", age <= max_load_age_h, f"last hour {last_load:%Y-%m-%d %H:%M}Z ({age:.1f} h ago)"))
    w = pl.read_parquet(PROCESSED_DIR / f"weather_vintages_{DATASET}.parquet")
    tomorrow_end = datetime.combine(now.date() + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    w_last = w.filter(pl.col("temperature_2m").is_not_null())["valid_at_utc"].max()
    checks.append(("weather covers tomorrow", w_last >= tomorrow_end - timedelta(hours=2), f"valid until {w_last:%Y-%m-%d %H:%M}Z"))
    tr = read_track()
    last_issue = tr["issued_at_utc"].max() if tr.height else None
    ok_track = last_issue is not None and (now - last_issue) <= timedelta(hours=30)
    checks.append(("live forecast issued in last 30 h", ok_track, f"last issued {last_issue}" if last_issue else "none"))
    for name, ok, detail in checks:
        typer.echo(f"{'OK  ' if ok else 'FAIL'} {name}: {detail}")
    if strict and not all(ok for _, ok, _ in checks):
        raise typer.Exit(1)


@app.command("build")
def build_all(skip_weather: bool = False) -> None:
    """One command: ingest (incremental), build the panel, and write the quality report."""
    ingest_smard_cmd()
    if not skip_weather:
        ingest_openmeteo_cmd()
    build_panel_cmd()
    quality_report_cmd()


if __name__ == "__main__":
    app()
