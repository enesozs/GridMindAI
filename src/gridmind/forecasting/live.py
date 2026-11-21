"""Live, append-only day-ahead forecasts (the public track record).

`issue_live(D)` makes the forecast for delivery day D *now*, with exactly the
information available now, and appends it to `track_record/live_forecasts.csv`. That
file is tracked in git: the commit history proves forecasts were never revised.

Rules:
- one forecast per delivery day; an existing day is never overwritten;
- `issued_at_utc` is the real wall-clock time; `on_time` = issued before the contractual
  issue time (D-1 10:00 Europe/Berlin). Late forecasts are kept but flagged and
  excluded from headline scores;
- weather = the fixed 48-h-lead forecast (made at or before valid - 48 h, so it is available at issue);
- the model is retrained on all data with actuals known at issue time (same code as the
  backtest).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl

from gridmind.config import PROCESSED_DIR, PROJECT_ROOT
from gridmind.contracts.issue_time import WEATHER_AVAILABILITY_LAG, IssueRule
from gridmind.features.build import assert_point_in_time, build_features
from gridmind.forecasting.backtest import TRAIN_START, model_specs
from gridmind.forecasting.models import QUANTILES
from gridmind.providers.openmeteo import DATASET as OM_DATASET

UTC = timezone.utc
TRACK = PROJECT_ROOT / "track_record" / "live_forecasts.csv"
MODEL = "gbm_weather"
SCHEMA = {
    "delivery_day": pl.Date, "valid_at_utc": pl.Datetime("us", "UTC"), "issued_at_utc": pl.Datetime("us", "UTC"),
    "contract_issue_time_utc": pl.Datetime("us", "UTC"), "on_time": pl.Boolean,
    "weather_model_run": pl.Datetime("us", "UTC"), "model": pl.String, "code_version": pl.String,
    **{k: pl.Float64 for k in QUANTILES},
}


def read_track() -> pl.DataFrame:
    if not TRACK.exists():
        return pl.DataFrame(schema=SCHEMA)
    return pl.read_csv(TRACK, schema=SCHEMA)


def issue_live(delivery_day: date, now: datetime | None = None, dataset: str = OM_DATASET) -> pl.DataFrame:
    from gridmind import __version__

    now = now or datetime.now(UTC)
    track = read_track()
    if delivery_day in track["delivery_day"].to_list():
        raise ValueError(f"forecast for {delivery_day} already issued; the track record is append-only")

    rule = IssueRule()
    contract_issue = rule.issue_time(delivery_day)
    # Use exactly the information available now. A run after the contract issue time is
    # kept but flagged on_time = False and excluded from headline scores.
    as_of = now

    class _AsOf(IssueRule):
        def issue_time(self, d: date) -> datetime:
            return as_of if d == delivery_day else super().issue_time(d)

        def last_known_load_end(self, d: date) -> datetime:
            if d == delivery_day:
                return (as_of - self.load_publication_lag).replace(minute=0, second=0, microsecond=0)
            return super().last_known_load_end(d)

    panel = pl.read_parquet(PROCESSED_DIR / "actuals_hourly.parquet")
    cal = pl.read_parquet(PROCESSED_DIR / "calendar_de.parquet")
    vint = pl.read_parquet(PROCESSED_DIR / f"weather_vintages_{dataset}.parquet")
    lag = WEATHER_AVAILABILITY_LAG[dataset]
    vint = vint.filter(pl.col("weather_model_run") + lag <= as_of)  # nothing from the future

    feats = build_features(panel, cal, vint, TRAIN_START, delivery_day, dataset=dataset, rule=_AsOf())
    assert_point_in_time(feats.filter(pl.col("delivery_day") == delivery_day).drop_nulls("weather_model_run"), dataset)
    known_cut = (as_of - timedelta(days=1)).date()
    train = feats.filter((pl.col("delivery_day") <= known_cut - timedelta(days=1)) & pl.col("y").is_not_null())
    target = feats.filter(pl.col("delivery_day") == delivery_day)

    spec = next(s for s in model_specs(include_oracle=False) if s.name == MODEL)
    model = spec.make()
    model.fit(train.drop_nulls(["y", *model.features]))
    pred = model.predict(target)
    out = target.select("delivery_day", "valid_at_utc", "weather_model_run").with_columns(
        issued_at_utc=pl.lit(now, pl.Datetime("us", "UTC")),
        contract_issue_time_utc=pl.lit(contract_issue, pl.Datetime("us", "UTC")),
        on_time=pl.lit(now <= contract_issue),
        model=pl.lit(MODEL), code_version=pl.lit(__version__),
        **{k: pl.Series(np.round(np.asarray(pred[k], dtype=float), 1)) for k in QUANTILES},
    ).select(list(SCHEMA))
    if out["q50"].null_count():
        raise RuntimeError("live forecast has missing values (weather or lag inputs unavailable)")
    TRACK.parent.mkdir(parents=True, exist_ok=True)
    pl.concat([track, out]).sort("valid_at_utc").write_csv(TRACK)
    return out


def score_track(panel: pl.DataFrame) -> pl.DataFrame:
    """Join actuals and the TSO forecast to the live forecasts (scored only where available)."""
    tr = read_track()
    load = panel.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == "actual_total_load")).select(
        pl.col("timestamp_utc").alias("valid_at_utc"), pl.col("value_mw").alias("y"))
    tso = panel.filter((pl.col("zone_id") == "DE_LU") & (pl.col("metric") == "tso_day_ahead_load_forecast")).select(
        pl.col("timestamp_utc").alias("valid_at_utc"), pl.col("value_mw").alias("tso_forecast"))
    return tr.join(load, on="valid_at_utc", how="left").join(tso, on="valid_at_utc", how="left")
