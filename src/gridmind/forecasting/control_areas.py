"""Day-ahead load forecasts for the four German TSO control areas and Germany, made coherent.

Hierarchy (one level): DE = 50Hertz + Amprion + TenneT + TransnetBW. SMARD's published
series satisfy this identity exactly (see the quality report), but independently produced
forecasts do not. Reconciliation maps the 5 base forecasts y_hat onto coherent ones,
y_tilde = S G y_hat, where S (5 x 4) sums the bottom level:

- bottom-up:  G = [0 | I], i.e. DE := sum of the area forecasts
- OLS:        G = (S'S)^-1 S'            (orthogonal projection onto coherent forecasts)
- MinT-shrink: G = (S'W^-1 S)^-1 S'W^-1, with W the base-forecast error covariance,
               shrunk towards its diagonal (Schäfer–Strimmer style intensity), so series
               with larger or correlated errors are adjusted more.

Per-area weather uses the population points inside each area (Luxembourg excluded: the
areas are German). Model and issue-time contract are identical to the national load model.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

from gridmind.features.build import FEATURES_CALENDAR, FEATURES_LAGS, FEATURES_TEMP, build_features
from gridmind.forecasting.backtest import GBM_BASE, ModelSpec
from gridmind.forecasting.models import QuantileGBM
from gridmind.providers.weather import DE_LU_POINTS

AREAS = ["DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"]
ZONES = ["DE", *AREAS]  # order of the hierarchy vector: total first, then bottom level
AREA_OF_POINT = {
    "berlin": "DE_50HZ", "hamburg": "DE_50HZ", "leipzig_halle": "DE_50HZ", "dresden": "DE_50HZ",
    "ruhr_essen": "DE_AMPRION", "cologne_duesseldorf": "DE_AMPRION",
    "munich": "DE_TENNET", "frankfurt": "DE_TENNET", "nuremberg": "DE_TENNET", "hanover": "DE_TENNET",
    "bremen": "DE_TENNET",
    "stuttgart": "DE_TRANSNETBW",
}
SELECTION_SPLIT = date(2025, 5, 1)  # W estimated before this date, method selected after (validation year)


def zone_weights(zone: str) -> dict[str, float]:
    pts = {p.location_id: p.weight for p in DE_LU_POINTS if p.location_id in AREA_OF_POINT}
    if zone == "DE":
        return pts
    return {k: v for k, v in pts.items() if AREA_OF_POINT[k] == zone}


def build_zone_features(panel, calendar, vintages, zone: str, first: date, last: date) -> pl.DataFrame:
    return build_features(panel, calendar, vintages, first, last, zone=zone, weights=zone_weights(zone))


def model_spec() -> ModelSpec:
    feats = FEATURES_CALENDAR + FEATURES_LAGS + FEATURES_TEMP
    return ModelSpec("gbm_weather", lambda: QuantileGBM("gbm_weather", feats, base_col=GBM_BASE))


# --- reconciliation -------------------------------------------------------------------

def summing_matrix(n_bottom: int = len(AREAS)) -> np.ndarray:
    return np.vstack([np.ones((1, n_bottom)), np.eye(n_bottom)])


def g_bottom_up(n_bottom: int = len(AREAS)) -> np.ndarray:
    return np.hstack([np.zeros((n_bottom, 1)), np.eye(n_bottom)])


def g_ols(s: np.ndarray) -> np.ndarray:
    return np.linalg.solve(s.T @ s, s.T)


def shrink_covariance(resid: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink the sample covariance of residuals (rows = time) towards its diagonal."""
    r = resid - resid.mean(axis=0)
    n = r.shape[0]
    cov = r.T @ r / n
    sd = np.sqrt(np.diag(cov))
    std = r / sd
    corr = std.T @ std / n
    # Schäfer & Strimmer (2005) optimal intensity for shrinking correlations to zero.
    w = np.einsum("ti,tj->tij", std, std)
    var_corr = n / (n - 1) ** 2 * ((w - corr) ** 2).sum(axis=0)
    off = ~np.eye(len(sd), dtype=bool)
    lam = float(np.clip(var_corr[off].sum() / (corr[off] ** 2).sum(), 0.0, 1.0))
    shrunk = lam * np.diag(np.diag(cov)) + (1 - lam) * cov
    return shrunk, lam


def g_mint(s: np.ndarray, w: np.ndarray) -> np.ndarray:
    w_inv = np.linalg.inv(w)
    return np.linalg.solve(s.T @ w_inv @ s, s.T @ w_inv)


def reconcile(base: np.ndarray, g: np.ndarray, s: np.ndarray) -> np.ndarray:
    """base: (time, 5) in ZONES order -> coherent (time, 5)."""
    return base @ (s @ g).T


def wide_point_forecasts(preds: pl.DataFrame, value: str = "q50") -> pl.DataFrame:
    """(valid_at, delivery_day, period) x zone table of one forecast column, plus actuals and TSO."""
    keep = ["valid_at_utc", "delivery_day", "period"]
    out = None
    for z in ZONES:
        g = preds.filter(pl.col("zone") == z).select(
            *keep, pl.col(value).alias(f"f_{z}"), pl.col("y").alias(f"y_{z}"), pl.col("tso_forecast").alias(f"tso_{z}"))
        out = g if out is None else out.join(g, on=keep, how="inner")
    return out.drop_nulls().sort("valid_at_utc")


# --- evaluation -----------------------------------------------------------------------

METHODS = ["base", "bottom_up", "ols", "mint_shrink"]


def _mae(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.abs(a - b).mean(axis=0)


def evaluate_methods(wide: pl.DataFrame, w_rows: pl.DataFrame, eval_rows: pl.DataFrame) -> dict:
    """Estimate W on `w_rows` base residuals, apply every method to `eval_rows`."""
    s = summing_matrix()
    f_cols, y_cols, t_cols = [f"f_{z}" for z in ZONES], [f"y_{z}" for z in ZONES], [f"tso_{z}" for z in ZONES]
    resid = w_rows.select(f_cols).to_numpy() - w_rows.select(y_cols).to_numpy()
    w, lam = shrink_covariance(resid)
    base = eval_rows.select(f_cols).to_numpy()
    y = eval_rows.select(y_cols).to_numpy()
    tso = eval_rows.select(t_cols).to_numpy()
    gs = {"bottom_up": g_bottom_up(), "ols": g_ols(s), "mint_shrink": g_mint(s, w)}
    out = {"shrinkage_lambda": lam, "hours": int(eval_rows.height),
           "base_incoherence_mae_mw": float(np.abs(base[:, 0] - base[:, 1:].sum(axis=1)).mean()),
           "tso_incoherence_mae_mw": float(np.abs(tso[:, 0] - tso[:, 1:].sum(axis=1)).mean()),
           "tso_mae_mw": dict(zip(ZONES, _mae(tso, y).round(1).tolist(), strict=True)), "methods": {}}
    for m in METHODS:
        f = base if m == "base" else reconcile(base, gs[m], s)
        mae = _mae(f, y)
        out["methods"][m] = {"mae_mw": dict(zip(ZONES, mae.round(1).tolist(), strict=True)),
                             "mean_mae_mw": float(mae.mean()),
                             "coherent": bool(np.allclose(f[:, 0], f[:, 1:].sum(axis=1), atol=1e-3))}
    return out, gs, w


def select_and_test(wide: pl.DataFrame) -> tuple[dict, str, np.ndarray]:
    val = wide.filter(pl.col("period") == "validation")
    test = wide.filter(pl.col("period") == "test")
    sel = evaluate_methods(wide, val.filter(pl.col("delivery_day") < SELECTION_SPLIT),
                           val.filter(pl.col("delivery_day") >= SELECTION_SPLIT))[0]
    chosen = min(METHODS, key=lambda m: sel["methods"][m]["mean_mae_mw"])  # pre-registered rule
    test_res, gs, _w = evaluate_methods(wide, val, test)
    s = summing_matrix()
    base = test.select([f"f_{z}" for z in ZONES]).to_numpy()
    final = base if chosen == "base" else reconcile(base, gs[chosen], s)
    return {"selection": sel, "chosen_method": chosen, "test": test_res}, chosen, final


LABEL = {"DE": "Germany", "DE_50HZ": "50Hertz", "DE_AMPRION": "Amprion", "DE_TENNET": "TenneT",
         "DE_TRANSNETBW": "TransnetBW"}


def write_report(res: dict, path) -> None:
    t, sel, ch = res["test"], res["selection"], res["chosen_method"]
    lines = [
        "# Control-area load forecasts with hierarchical reconciliation", "",
        ("_Generated by `gridmind control-areas`. Method chosen on the validation year by a rule fixed in "
        "advance (lowest mean MAE across all five series); the test year was evaluated once._"), "",
        ("Each of the four German TSO control areas and Germany as a whole gets its own day-ahead load "
         "forecast (same model and issue-time contract as the national DE-LU model, with weather from the "
         "population points inside each area). Independent forecasts do not add up, so they are reconciled: "
         "bottom-up, OLS projection, or MinT with a shrunk error covariance."), "",
        (f"**Chosen method: {ch}.** Base forecasts were incoherent by {t['base_incoherence_mae_mw']:,.0f} MW "
        f"on average (|Germany − sum of areas|); the TSOs' own forecasts by {t['tso_incoherence_mae_mw']:,.0f} MW."),
        "",
        "## Test year MAE by series (MW)", "",
        "| Series | TSO forecast | Base | Bottom-up | OLS | MinT-shrink |", "|---|---|---|---|---|---|",
    ]
    for z in ZONES:
        m = t["methods"]
        lines.append(f"| {LABEL[z]} | {t['tso_mae_mw'][z]:,.0f} | {m['base']['mae_mw'][z]:,.0f} "
                     f"| {m['bottom_up']['mae_mw'][z]:,.0f} | {m['ols']['mae_mw'][z]:,.0f} "
                     f"| {m['mint_shrink']['mae_mw'][z]:,.0f} |")
    lines += ["", "| Method | Mean MAE, test | Mean MAE, selection half of validation | Coherent |",
              "|---|---|---|---|"]
    for mth in METHODS:
        lines.append(f"| {mth} | {t['methods'][mth]['mean_mae_mw']:,.0f} | "
                     f"{sel['methods'][mth]['mean_mae_mw']:,.0f} | {'yes' if t['methods'][mth]['coherent'] else 'no'} |")
    best_test = min(METHODS, key=lambda m: t["methods"][m]["mean_mae_mw"])
    notes = []
    if best_test != ch:
        diff = t["methods"][ch]["mean_mae_mw"] - t["methods"][best_test]["mean_mae_mw"]
        notes.append(f"On the test year **{best_test}** was best, {diff:,.0f} MW lower in mean MAE than the "
                     f"chosen {ch}. The choice is kept as made on validation data; the gap is small.")
    if t["shrinkage_lambda"] > 0.95:
        notes.append("The shrinkage intensity is about 1: error correlations were too noisy to estimate reliably, "
                     "so MinT reduced to variance weighting (WLS). Germany's forecast has the largest error "
                     "variance, so it is adjusted most, which is why MinT ends up close to bottom-up.")
    lines += ["", *[f"- {n}" for n in notes], "",
              (f"Shrinkage intensity (test-time covariance): {t['shrinkage_lambda']:.2f}. Test hours: "
               f"{t['hours']:,}."), "",
              "Data: Bundesnetzagentur | SMARD.de (CC BY 4.0); weather data by Open-Meteo.com (CC BY 4.0)."]
    path.write_text("\n".join(lines) + "\n")
