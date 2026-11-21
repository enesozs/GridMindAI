"""Rolling-origin backtest with monthly refits and a frozen test year.

For each month M: train on delivery days whose actuals were known before the first
issue of M (delivery_day <= M_start - 2 days), then forecast every delivery day of M.
Hyperparameters are fixed in code before the test year is evaluated; the test year
(see docs/DATA_CONTRACT.md) is never used to choose between configurations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl

from gridmind import __version__
from gridmind.features.build import (
    FEATURES_CALENDAR,
    FEATURES_LAGS,
    FEATURES_TEMP,
    FEATURES_TEMP_ORACLE,
)
from gridmind.forecasting.models import (
    HGB_PARAMS,
    QUANTILES,
    HolidayNaive,
    NaiveModel,
    QuantileGBM,
    RidgeModel,
)

UTC = timezone.utc
VALIDATION = (date(2024, 11, 1), date(2025, 10, 31))
TEST = (date(2025, 11, 1), date(2026, 10, 31))
TRAIN_START = date(2021, 5, 20)
# Chosen on the VALIDATION year only (docs/reports/load_model_selection.md): ratio to the last 24 known
# hours + temperature-only weather had the lowest pinball loss (476 vs 553 all-weather, 603 absolute).
GBM_BASE: str | None = "recent_24h_mean"

@dataclass(frozen=True)
class ModelSpec:
    name: str
    make: Callable[[], object]
    label: str = "operational"  # or "hindsight_oracle"


def model_specs(include_oracle: bool = True) -> list[ModelSpec]:
    specs = [
        ModelSpec("naive_d7", lambda: NaiveModel("naive_d7", "lag_d7")),
        ModelSpec("naive_d2", lambda: NaiveModel("naive_d2", "lag_d2")),
        ModelSpec("naive_holiday_adjusted", HolidayNaive),
        ModelSpec("ridge_calendar_lags", lambda: RidgeModel(
            "ridge_calendar_lags",
            ["holiday_pop_share", "doy_sin", "doy_cos", "holiday_share_d7", *FEATURES_LAGS])),
        ModelSpec("gbm_no_weather", lambda: QuantileGBM("gbm_no_weather", FEATURES_CALENDAR + FEATURES_LAGS,
                                                         base_col=GBM_BASE)),
        ModelSpec("gbm_weather", lambda: QuantileGBM(
            "gbm_weather", FEATURES_CALENDAR + FEATURES_LAGS + FEATURES_TEMP, base_col=GBM_BASE)),
    ]
    if include_oracle:
        specs.append(ModelSpec("gbm_oracle_weather", lambda: QuantileGBM(
            "gbm_oracle_weather", FEATURES_CALENDAR + FEATURES_LAGS + FEATURES_TEMP_ORACLE, base_col=GBM_BASE),
            label="hindsight_oracle"))
    return specs


def month_starts(first: date, last: date) -> list[date]:
    out, d = [], date(first.year, first.month, 1)
    while d <= last:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _fold_frames(feat: pl.DataFrame, m: date) -> tuple[pl.DataFrame, pl.DataFrame]:
    nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    train = feat.filter((pl.col("delivery_day") >= TRAIN_START) & (pl.col("delivery_day") <= m - timedelta(days=2)))
    test = feat.filter((pl.col("delivery_day") >= m) & (pl.col("delivery_day") < nxt))
    return train, test


def run_backtest(feat: pl.DataFrame, period: tuple[date, date], specs: list[ModelSpec], log=print) -> pl.DataFrame:
    rows = []
    for m in month_starts(*period):
        train, test = _fold_frames(feat, m)
        if test.is_empty():
            continue
        for spec in specs:
            model = spec.make()
            need = [c for c in getattr(model, "features", []) if c in train.columns]
            tr = train.drop_nulls(["y", *need]) if need else train.drop_nulls(["y"])
            model.fit(tr)
            pred = model.predict(test)
            base = test.select("delivery_day", "issue_time_utc", "valid_at_utc", "lead_hours", "local_hour", "y",
                               "tso_forecast", "wx_t2m_day_mean", "holiday_pop_share")
            rows.append(base.with_columns(
                model=pl.lit(spec.name), label=pl.lit(spec.label), fold=pl.lit(m.isoformat()),
                **{k: pl.Series(np.asarray(pred[k], dtype=float)) for k in QUANTILES},
            ))
        log(f"  fold {m:%Y-%m}: train {train.height} rows, test {test.height}")
    return pl.concat(rows).with_columns(pl.col(k).fill_nan(None) for k in QUANTILES)


def run_manifest(period_name: str, period: tuple[date, date], feat: pl.DataFrame, specs: list[ModelSpec]) -> dict:
    payload = {
        "period": period_name,
        "from": period[0].isoformat(),
        "to": period[1].isoformat(),
        "code_version": __version__,
        "models": [s.name for s in specs],
        "hgb_params": HGB_PARAMS,
        "feature_rows": feat.height,
        "feature_columns": sorted(feat.columns),
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    payload["run_id"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return payload
