"""Incremental SMARD ingestion into an interval-level actuals table.

Weekly files older than `refresh_weeks` are fetched once and reused from the raw store
(the manifest maps metric/region/week to a raw file). Recent weeks are always
re-fetched because SMARD revises them. Each normalized row keeps the raw SHA-256 and
the source's own `created` timestamp, for lineage.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from gridmind.config import PROCESSED_DIR, RAW_DIR
from gridmind.providers import smard
from gridmind.storage import read_manifest

UTC = timezone.utc

# What we pull, per region. DE-LU gets the full generation mix; the national and
# control-area regions get what the Atlas needs.
PLAN: dict[str, list[str]] = {
    "DE-LU": list(smard.FILTERS),
    "DE": ["actual_total_load", "tso_day_ahead_load_forecast", "residual_load", "gen_solar", "gen_wind_onshore"],
    "50Hertz": ["actual_total_load", "tso_day_ahead_load_forecast", "gen_solar", "gen_wind_onshore"],
    "Amprion": ["actual_total_load", "tso_day_ahead_load_forecast", "gen_solar", "gen_wind_onshore"],
    "TenneT": ["actual_total_load", "tso_day_ahead_load_forecast", "gen_solar", "gen_wind_onshore"],
    "TransnetBW": ["actual_total_load", "tso_day_ahead_load_forecast", "gen_solar", "gen_wind_onshore"],
}

ZONE_ID = {"DE-LU": "DE_LU", "DE": "DE", "50Hertz": "DE_50HZ", "Amprion": "DE_AMPRION",
           "TenneT": "DE_TENNET", "TransnetBW": "DE_TRANSNETBW"}


def _cached(raw_dir: Path) -> dict[tuple[str, str, int], dict]:
    out: dict[tuple[str, str, int], dict] = {}
    for rec in read_manifest(raw_dir):
        if rec["source"] != smard.SOURCE:
            continue
        p = rec["params"]
        out[(rec["dataset"], p["region"], int(p["week_ts"]))] = rec  # last write wins
    return out


def ingest(
    start: datetime,
    end: datetime | None = None,
    plan: dict[str, list[str]] | None = None,
    refresh_weeks: int = 6,
    pause_s: float = 0.05,
    workers: int = 4,
    raw_dir: Path = RAW_DIR,
    log=print,
) -> pl.DataFrame:
    plan = plan or PLAN
    end = end or datetime.now(UTC)
    fresh_cutoff = (end - timedelta(weeks=refresh_weeks)).timestamp() * 1000
    cache = _cached(raw_dir)
    c = smard.client()
    frames: list[pl.DataFrame] = []
    n_fetched = n_cached = n_missing = 0
    for region, metrics in plan.items():
        for metric in metrics:
            try:
                weeks = smard.week_index(c, metric, region)
            except FileNotFoundError:
                log(f"  {region}/{metric}: no index (404), skipped")
                n_missing += 1
                continue
            weeks = [w for w in weeks if start.timestamp() * 1000 - 7 * 86400_000 <= w < end.timestamp() * 1000]
            results: list[tuple[pl.DataFrame, datetime | None, str]] = []
            to_fetch = []
            for w in weeks:
                rec = cache.get((metric, region, w))
                if rec is not None and w < fresh_cutoff and (raw_dir / rec["path"]).exists():
                    rows, created = smard.parse_week((raw_dir / rec["path"]).read_bytes(), "quarterhour")
                    results.append((rows, created, rec["sha256"]))
                    n_cached += 1
                else:
                    to_fetch.append(w)

            def _fetch(w: int, metric: str = metric, region: str = region):
                wk = smard.fetch_week(c, metric, region, w)
                time.sleep(pause_s)
                return wk.rows, wk.created_utc, wk.record.sha256

            with ThreadPoolExecutor(max_workers=workers) as ex:
                results.extend(ex.map(_fetch, to_fetch))
            n_fetched += len(to_fetch)
            for rows, created, sha in results:
                frames.append(
                    rows.with_columns(
                        zone_id=pl.lit(ZONE_ID[region]),
                        metric=pl.lit(metric),
                        source=pl.lit("smard"),
                        source_created_utc=pl.lit(created, dtype=pl.Datetime("us", "UTC")),
                        raw_sha256=pl.lit(sha),
                    )
                )
            log(f"  {region}/{metric}: {len(weeks)} weeks")
    log(f"SMARD: fetched {n_fetched}, from cache {n_cached}, missing series {n_missing}")
    df = pl.concat(frames, how="vertical_relaxed")
    df = df.filter((pl.col("timestamp_utc") >= start) & (pl.col("timestamp_utc") < end))
    return df.select(
        "zone_id", "metric", "timestamp_utc", "resolution_minutes", "value_mw", "energy_mwh",
        "source", "source_created_utc", "raw_sha256",
    ).sort("zone_id", "metric", "timestamp_utc")


def write_actuals(df: pl.DataFrame, processed_dir: Path = PROCESSED_DIR) -> Path:
    """Merge into the processed table: new rows replace existing rows with the same
    (zone, metric, interval); rows outside the new pull are kept (incremental runs)."""
    processed_dir.mkdir(parents=True, exist_ok=True)
    keys = ["zone_id", "metric", "timestamp_utc"]
    dup = df.group_by(keys).len().filter(pl.col("len") > 1)
    if dup.height:
        raise ValueError(f"duplicate actual intervals: {dup.height}")
    path = processed_dir / "actuals_qh.parquet"
    if path.exists():
        old = pl.read_parquet(path)
        df = pl.concat([old.join(df.select(keys), on=keys, how="anti"), df], how="vertical_relaxed")
    df.sort(keys).write_parquet(path)
    return path
