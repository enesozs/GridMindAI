"""Forecast models. Every model maps a feature frame to point + quantile predictions.

Output columns: `q05, q25, q50, q75, q95` (MW). For deterministic baselines the
intervals come from empirical residual quantiles on the training window, so every
model is scored on the same probabilistic metrics.

Gradient boosting uses scikit-learn's HistGradientBoostingRegressor with quantile
loss (same model family as LightGBM, with no OpenMP system dependency). Intervals are
calibrated with conformalized quantile regression (CQR, Romano et al. 2019) on the most
recent weeks of the training window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl
from joblib import Parallel, delayed
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

QUANTILES = {"q05": 0.05, "q25": 0.25, "q50": 0.5, "q75": 0.75, "q95": 0.95}
HGB_PARAMS = {"max_iter": 600, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 40,
                  "l2_regularization": 1.0, "random_state": 42}


def _fit_one(x: np.ndarray, y: np.ndarray, alpha: float) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss="quantile", quantile=alpha, **HGB_PARAMS).fit(x, y)


def _residual_bands(point: np.ndarray, resid: np.ndarray) -> dict[str, np.ndarray]:
    qs = {k: np.nanquantile(resid, v) for k, v in QUANTILES.items()}
    out = {k: point + qs[k] - qs["q50"] for k in QUANTILES}
    out["q50"] = point
    return out


@dataclass
class NaiveModel:
    """Seasonal naive using a lag column; intervals from training residual quantiles."""
    name: str
    lag_col: str
    resid: np.ndarray = field(default_factory=lambda: np.array([]))

    def fit(self, df: pl.DataFrame) -> NaiveModel:
        self.resid = (df["y"] - df[self.lag_col]).drop_nulls().to_numpy()
        return self

    def predict(self, df: pl.DataFrame) -> dict[str, np.ndarray]:
        return _residual_bands(df[self.lag_col].to_numpy().astype(float), self.resid)


@dataclass
class HolidayNaive:
    """D-7 same hour; D-14 when D-7 was a holiday and D is not; D-7 scaled by the learned
    holiday/normal-day ratio when D is a holiday and D-7 was not."""
    name: str = "naive_holiday_adjusted"
    holiday_ratio: float = 1.0
    resid: np.ndarray = field(default_factory=lambda: np.array([]))

    def _point(self, df: pl.DataFrame) -> np.ndarray:
        d_hol = df["holiday_pop_share"].to_numpy() > 0.5
        d7_hol = df["holiday_share_d7"].fill_null(0).to_numpy() > 0.5
        p = df["lag_d7"].to_numpy().astype(float).copy()
        swap = d7_hol & ~d_hol
        p[swap] = df["lag_d14"].to_numpy()[swap]
        # Holiday after a normal week: scale D-7 by the holiday/normal ratio learned in training.
        p[d_hol & ~d7_hol] *= self.holiday_ratio
        return p

    def fit(self, df: pl.DataFrame) -> HolidayNaive:
        h = df.filter((pl.col("holiday_pop_share") > 0.5) & (pl.col("holiday_share_d7").fill_null(0) <= 0.5))
        r = (h["y"] / h["lag_d7"]).drop_nulls()
        self.holiday_ratio = float(r.median()) if r.len() else 1.0
        self.resid = (df["y"].to_numpy() - self._point(df))
        self.resid = self.resid[~np.isnan(self.resid)]
        return self

    def predict(self, df: pl.DataFrame) -> dict[str, np.ndarray]:
        return _residual_bands(self._point(df), self.resid)


@dataclass
class RidgeModel:
    """Linear benchmark: one-hot hour x weekday + calendar + lag features (no weather)."""
    name: str
    numeric: list[str]
    model: object = None
    resid: np.ndarray = field(default_factory=lambda: np.array([]))

    def _x(self, df: pl.DataFrame):
        x = df.select(*self.numeric, "local_hour", "day_of_week").to_pandas()
        x["hour_dow"] = x["local_hour"].astype(str) + "_" + x["day_of_week"].astype(str)
        return x

    def fit(self, df: pl.DataFrame) -> RidgeModel:
        df = df.drop_nulls([*self.numeric, "y"])
        ct = ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["hour_dow"]),
            ("num", StandardScaler(), self.numeric),
        ])
        self.model = make_pipeline(ct, Ridge(alpha=1.0)).fit(self._x(df), df["y"].to_numpy())
        self.resid = df["y"].to_numpy() - self.model.predict(self._x(df))
        return self

    def predict(self, df: pl.DataFrame) -> dict[str, np.ndarray]:
        x = self._x(df)
        ok = ~x[self.numeric].isna().any(axis=1).to_numpy()
        point = np.full(len(x), np.nan)
        point[ok] = self.model.predict(x[ok])
        return _residual_bands(point, self.resid)


@dataclass
class QuantileGBM:
    """One HGB quantile model per quantile, with CQR calibration of the 50% and 90% bands."""
    name: str
    features: list[str]
    calib_weeks: int = 8
    # Optional level normalisation: learn y / base (e.g. the mean of the last 24 known
    # hours). Trees cannot extrapolate beyond the training range; a ratio target lets the
    # model learn shape relative to the current level. base must be known at issue time.
    base_col: str | None = None
    models: dict = field(default_factory=dict)
    cqr: dict = field(default_factory=dict)

    def _target(self, df: pl.DataFrame) -> np.ndarray:
        y = df["y"].to_numpy()
        return y / df[self.base_col].to_numpy() if self.base_col else y

    def _fit_models(self, df: pl.DataFrame) -> dict:
        x, y = df.select(self.features).to_numpy(), self._target(df)
        # One single-threaded process per quantile: measured ~2x faster per fit than the
        # default OpenMP threading (which oversubscribes the CPU), and the 5 fits run in parallel.
        fitted = Parallel(n_jobs=len(QUANTILES), backend="loky", inner_max_num_threads=1)(
            delayed(_fit_one)(x, y, a) for a in QUANTILES.values())
        return dict(zip(QUANTILES, fitted, strict=True))

    def _raw(self, models: dict, df: pl.DataFrame) -> dict[str, np.ndarray]:
        x = df.select(self.features).to_numpy()
        scale = df[self.base_col].to_numpy() if self.base_col else 1.0
        out = {k: m.predict(x) * scale for k, m in models.items()}
        stacked = np.sort(np.vstack([out[k] for k in QUANTILES]), axis=0)  # remove quantile crossing
        return {k: stacked[i] for i, k in enumerate(QUANTILES)}

    def fit(self, df: pl.DataFrame) -> QuantileGBM:
        df = df.drop_nulls(["y", self.base_col] if self.base_col else "y")
        cut = df["valid_at_utc"].max() - pl.duration(weeks=self.calib_weeks)
        cut_val = df.select(cut).item()
        proper, calib = df.filter(pl.col("valid_at_utc") < cut_val), df.filter(pl.col("valid_at_utc") >= cut_val)
        pred = self._raw(self._fit_models(proper), calib)
        y = calib["y"].to_numpy()
        for lo, hi, alpha in [("q05", "q95", 0.10), ("q25", "q75", 0.50)]:
            s = np.maximum(pred[lo] - y, y - pred[hi])
            n = len(s)
            level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
            self.cqr[(lo, hi)] = float(np.quantile(s, level))
        self.models = self._fit_models(df)  # refit on all data; keep the CQR offsets
        return self

    def predict(self, df: pl.DataFrame) -> dict[str, np.ndarray]:
        out = self._raw(self.models, df)
        for (lo, hi), q in self.cqr.items():
            out[lo] = out[lo] - q
            out[hi] = out[hi] + q
        return out
