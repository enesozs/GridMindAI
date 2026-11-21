"""Benchmark report: leaderboard, significance tests, breakdowns and figures."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from gridmind.analytics.metrics import (
    diebold_mariano,
    peak_mae,
    point_metrics,
    probabilistic_metrics,
)

TSO = "tso_official"


def scored_rows(pred: pl.DataFrame) -> pl.DataFrame:
    """Hours where the target, the TSO forecast and every model's median exist."""
    n_models = pred["model"].n_unique()
    ok = (
        pred.filter(pl.col("y").is_not_null() & pl.col("tso_forecast").is_not_null() & pl.col("q50").is_not_null())
        .group_by("valid_at_utc").agg(pl.len().alias("n")).filter(pl.col("n") == n_models)
    )
    return pred.join(ok.select("valid_at_utc"), on="valid_at_utc", how="inner")


def leaderboard(s: pl.DataFrame) -> pl.DataFrame:
    rows = []
    tso = s.filter(pl.col("model") == s["model"][0]).with_columns(q50=pl.col("tso_forecast"))
    rows.append({"model": TSO, "label": "official benchmark", **point_metrics(tso), "peak_mae_mw": peak_mae(tso)})
    for (name, label), g in s.group_by("model", "label", maintain_order=True):
        rows.append({"model": name, "label": label, **point_metrics(g), "peak_mae_mw": peak_mae(g),
                     **probabilistic_metrics(g)})
    lb = pl.DataFrame(rows)
    tso_mae = lb.filter(pl.col("model") == TSO)["mae_mw"][0]
    return lb.with_columns(skill_vs_tso=1 - pl.col("mae_mw") / tso_mae).sort("mae_mw")


def daily_abs_err(s: pl.DataFrame, model: str | None) -> pl.DataFrame:
    g = s.filter(pl.col("model") == (model or s["model"][0]))
    col = pl.col("tso_forecast") if model is None else pl.col("q50")
    return g.group_by("delivery_day").agg(e=(col - pl.col("y")).abs().mean()).sort("delivery_day")


def dm_tests(s: pl.DataFrame, pairs: list[tuple[str, str | None]]) -> list[dict]:
    out = []
    for a, b in pairs:
        ea, eb = daily_abs_err(s, a), daily_abs_err(s, b)
        j = ea.join(eb, on="delivery_day", suffix="_b")
        out.append({"model": a, "vs": b or TSO, **diebold_mariano(j["e"].to_numpy(), j["e_b"].to_numpy())})
    return out


def breakdowns(s: pl.DataFrame, models: list[str]) -> dict:
    sub = s.filter(pl.col("model").is_in(models))
    tso = s.filter(pl.col("model") == models[0]).with_columns(model=pl.lit(TSO), q50=pl.col("tso_forecast"))
    both = pl.concat([sub, tso], how="diagonal_relaxed").with_columns(ae=(pl.col("q50") - pl.col("y")).abs())
    temp_bin = (
        pl.when(pl.col("wx_t2m_day_mean") < 0).then(pl.lit("<0°C"))
        .when(pl.col("wx_t2m_day_mean") < 10).then(pl.lit("0–10°C"))
        .when(pl.col("wx_t2m_day_mean") < 20).then(pl.lit("10–20°C")).otherwise(pl.lit("≥20°C"))
    )
    return {
        "by_hour": both.group_by("model", "local_hour").agg(mae=pl.col("ae").mean()).sort("model", "local_hour"),
        "by_month": both.with_columns(month=pl.col("delivery_day").dt.strftime("%Y-%m"))
        .group_by("model", "month").agg(mae=pl.col("ae").mean()).sort("model", "month"),
        "by_temp": both.with_columns(temp_bin=temp_bin).group_by("model", "temp_bin")
        .agg(mae=pl.col("ae").mean(), hours=pl.len()).sort("model", "temp_bin"),
        "holidays": both.with_columns(day_type=pl.when(pl.col("holiday_pop_share") > 0.5).then(pl.lit("holiday"))
                                      .otherwise(pl.lit("regular")))
        .group_by("model", "day_type").agg(mae=pl.col("ae").mean(), hours=pl.len()).sort("model", "day_type"),
    }


PALETTE = {"tso_official": "#6b7280", "gbm_weather": "#2563eb", "gbm_no_weather": "#93c5fd",
           "naive_d7": "#d97706", "ridge_calendar_lags": "#059669", "gbm_oracle_weather": "#7c3aed"}


def _style(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def figures(s: pl.DataFrame, bd: dict, out: Path, period: str) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for m, g in bd["by_hour"].group_by("model", maintain_order=True):
        name = m[0]
        if name in PALETTE:
            ax.plot(g["local_hour"], g["mae"], label=name, color=PALETTE[name], lw=2 if name in (TSO, "gbm_weather")
                    else 1.2)
    _style(ax, f"MAE by local hour of day — {period}", "MAE (MW)")
    ax.set_xlabel("Hour (Europe/Berlin)")
    ax.legend(frameon=False, fontsize=8, ncol=3)
    f = out / f"mae_by_hour_{period}.png"
    fig.tight_layout()
    fig.savefig(f, dpi=150)
    plt.close(fig)
    files.append(f.name)

    fig, ax = plt.subplots(figsize=(8, 3.6))
    for m, g in bd["by_month"].group_by("model", maintain_order=True):
        name = m[0]
        if name in (TSO, "gbm_weather", "naive_d7", "gbm_no_weather"):
            ax.plot(g["month"], g["mae"], marker="o", label=name, color=PALETTE[name])
    _style(ax, f"MAE by month — {period}", "MAE (MW)")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.legend(frameon=False, fontsize=8)
    f = out / f"mae_by_month_{period}.png"
    fig.tight_layout()
    fig.savefig(f, dpi=150)
    plt.close(fig)
    files.append(f.name)

    # Example fortnight fan chart (most recent two weeks in the period).
    g = s.filter(pl.col("model") == "gbm_weather").sort("valid_at_utc")
    last = g["delivery_day"].max()
    w = g.filter(pl.col("delivery_day") > last - pl.duration(days=14))
    t = w["valid_at_utc"].to_numpy()
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.fill_between(t, w["q05"], w["q95"], color="#2563eb", alpha=0.15, label="90% interval")
    ax.fill_between(t, w["q25"], w["q75"], color="#2563eb", alpha=0.30, label="50% interval")
    ax.plot(t, w["q50"], color="#2563eb", lw=1.4, label="GridMind median")
    ax.plot(t, w["tso_forecast"], color="#6b7280", lw=1, ls="--", label="TSO day-ahead forecast")
    ax.plot(t, w["y"], color="#111827", lw=1.2, label="Actual")
    _style(ax, f"Day-ahead load forecasts, last 14 days of {period}", "Load (MW)")
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper left")
    f = out / f"fan_chart_{period}.png"
    fig.tight_layout()
    fig.savefig(f, dpi=150)
    plt.close(fig)
    files.append(f.name)
    return files


def _md_table(df: pl.DataFrame, cols: list[str], fmt: dict[str, str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for r in df.select(cols).to_dicts():
        cells = []
        for c in cols:
            v = r[c]
            cells.append("—" if v is None or (isinstance(v, float) and np.isnan(v)) else
                         (format(v, fmt[c]) if c in fmt and isinstance(v, (int, float)) else str(v)))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def write_report(results: dict, path: Path) -> None:
    fmt = {"mae_mw": ",.0f", "rmse_mw": ",.0f", "bias_mw": "+,.0f", "mape_pct": ".2f", "peak_mae_mw": ",.0f",
           "pinball_mean_mw": ",.0f", "coverage_90": ".3f", "coverage_50": ".3f", "width_90_mw": ",.0f",
           "width_50_mw": ",.0f", "skill_vs_tso": "+.1%", "dm_stat": "+.2f", "p_value": ".4f", "mae": ",.0f"}
    lines = [
        "# Day-ahead load forecast benchmark (DE-LU)", "",
        "_Generated by `gridmind backtest`. Do not edit by hand; numbers come from the run manifests below._", "",
        "**Setup.**",
        "- Forecasts are issued at D-1 10:00 Europe/Berlin (the TSO publication deadline) for each hour of D.",
        "- Weather comes from the GFS run available at issue time; load lags are only those known at issue time.",
        ("- Models are refit monthly with expanding windows. The test year was evaluated once, with "
        "hyperparameters fixed beforehand."),
        "- Scored hours are those where the target, the TSO forecast and every model exist.",
        ("- Skill = 1 − MAE / MAE(TSO). The DM test uses daily mean absolute errors with Newey-West variance "
        "(negative = first model better)."),
        ("- `gbm_oracle_weather` uses GFS *analysis* (hindsight) weather: an upper bound, **not** an "
        "operational forecast."),
        "",
    ]
    for period, r in results.items():
        lines += [f"## {period.capitalize()} period: {r['manifest']['from']} → {r['manifest']['to']}", "",
                  f"Run id `{r['manifest']['run_id']}` · scored hours: {r['n_hours']:,}", "",
                  _md_table(r["leaderboard"], ["model", "label", "mae_mw", "rmse_mw", "bias_mw", "mape_pct",
                                               "peak_mae_mw", "skill_vs_tso", "pinball_mean_mw", "coverage_50",
                                               "coverage_90", "width_90_mw"], fmt),
                  "**Significance (Diebold–Mariano)**", "",
                  _md_table(pl.DataFrame(r["dm"]), ["model", "vs", "dm_stat", "p_value", "n_days"], fmt),
                  "**MAE by daily-mean forecast temperature**", "",
                  _md_table(r["breakdowns"]["by_temp"], ["model", "temp_bin", "mae", "hours"], fmt),
                  "**Holidays vs regular days**", "",
                  _md_table(r["breakdowns"]["holidays"], ["model", "day_type", "mae", "hours"], fmt)]
        lines += [f"![{f}](figures/{f})" for f in r["figures"]] + [""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    (path.parent / "load_manifests.json").write_text(
        json.dumps({k: v["manifest"] for k, v in results.items()}, indent=2, default=str))
    (path.parent / "load_leaderboard.json").write_text(json.dumps({
        k: {"run_id": v["manifest"]["run_id"], "from": v["manifest"]["from"], "to": v["manifest"]["to"],
            "n_hours": v["n_hours"], "leaderboard": v["leaderboard"].to_dicts(), "dm": v["dm"],
            "by_hour": v["breakdowns"]["by_hour"].to_dicts(), "by_month": v["breakdowns"]["by_month"].to_dicts(),
            "by_temp": v["breakdowns"]["by_temp"].to_dicts()}
        for k, v in results.items()}, indent=2, default=str))
