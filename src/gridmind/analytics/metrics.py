"""Forecast evaluation metrics (all in MW unless stated)."""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from gridmind.forecasting.models import QUANTILES


def pinball(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def point_metrics(df: pl.DataFrame, pred: str = "q50") -> dict:
    e = (df[pred] - df["y"]).to_numpy()
    y = df["y"].to_numpy()
    return {
        "mae_mw": float(np.mean(np.abs(e))),
        "rmse_mw": float(np.sqrt(np.mean(e**2))),
        "bias_mw": float(np.mean(e)),
        # MAPE only where the target is far from zero (load); undefined for solar nights.
        "mape_pct": float(np.mean(np.abs(e) / y) * 100) if np.nanmin(y) > 1000 else float("nan"),
    }


def peak_mae(df: pl.DataFrame, pred: str = "q50") -> float:
    """Error on each day's peak hour (actual max vs forecast at that hour)."""
    idx = df.group_by("delivery_day").agg(pl.col("y").arg_max().alias("i"), pl.col("y").max().alias("ymax"),
                                          pl.col(pred).gather(pl.col("y").arg_max()).first().alias("p"))
    return float((idx["p"] - idx["ymax"]).abs().mean())


def probabilistic_metrics(df: pl.DataFrame) -> dict:
    y = df["y"].to_numpy()
    out = {"pinball_mean_mw": float(np.mean([pinball(y, df[k].to_numpy(), a) for k, a in QUANTILES.items()]))}
    for lo, hi, nom in [("q05", "q95", 0.90), ("q25", "q75", 0.50)]:
        inside = (y >= df[lo].to_numpy()) & (y <= df[hi].to_numpy())
        out[f"coverage_{int(nom * 100)}"] = float(inside.mean())
        out[f"width_{int(nom * 100)}_mw"] = float(np.mean(df[hi].to_numpy() - df[lo].to_numpy()))
    return out


def diebold_mariano(e1: np.ndarray, e2: np.ndarray, lag: int = 7) -> dict:
    """DM test on daily mean absolute errors (model 1 vs model 2), Newey-West variance.

    Negative statistic = model 1 has lower loss. Aggregating to days removes the strong
    within-day error correlation; `lag` handles day-to-day autocorrelation.
    """
    d = np.abs(e1) - np.abs(e2)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return {"dm_stat": None, "p_value": None, "n_days": n}
    dc = d - d.mean()
    var = np.sum(dc**2) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        var += 2 * w * np.sum(dc[k:] * dc[:-k]) / n
    stat = d.mean() / math.sqrt(var / n)
    p = math.erfc(abs(stat) / math.sqrt(2))  # two-sided normal approximation
    return {"dm_stat": float(stat), "p_value": float(p), "n_days": n}
