"""SMARD (Bundesnetzagentur) market-data adapter. No API key required.

Licence (checked 2026-11-14, smard.de/en/datennutzung): market data are CC BY 4.0,
attribution "Bundesnetzagentur | SMARD.de". EXCEPTION: SMARD states that licensing of
WHOLESALE PRICES is under legal review (HEDWIG proceedings), so GridMind does not use
SMARD price series. SMARD obtains the data from ENTSO-E; we attribute both.

Endpoint: https://www.smard.de/app/chart_data/{filter}/{region}/index_{resolution}.json
returns weekly file start timestamps (ms since epoch, UTC), and
.../{filter}/{region}/{filter}_{region}_{resolution}_{ts}.json returns
{"meta_data": {"created": ms}, "series": [[interval_start_ms, value | null], ...]}.

UNITS: SMARD quarter-hour/hour values for consumption and generation are ENERGY per
interval (MWh), not power. Mean power MW = MWh / interval_hours. (Verified on a real
week: about 13,300 MWh per 15 min = about 53 GW German load.)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import polars as pl

from gridmind.storage import RawRecord, store_raw

BASE = "https://www.smard.de/app/chart_data"
SOURCE = "smard"
LICENCE = "CC-BY-4.0, attribution 'Bundesnetzagentur | SMARD.de' (data originally from ENTSO-E)"
USER_AGENT = "GridMindAI research pipeline (non-commercial)"

# Filter ids -> canonical metric names. Unit of all of these: MWh per interval.
FILTERS: dict[str, int] = {
    "actual_total_load": 410,
    "tso_day_ahead_load_forecast": 411,
    "residual_load": 4359,
    "gen_solar": 4068,
    "gen_wind_onshore": 4067,
    "gen_wind_offshore": 1225,
    "gen_lignite": 1223,
    "gen_hard_coal": 4069,
    "gen_gas": 4071,
    "gen_nuclear": 1224,
    "gen_hydro": 1226,
    "gen_biomass": 4066,
    "gen_other_renewable": 1228,
    "gen_other_conventional": 1227,
    "gen_pumped_storage": 4070,
    # TSO day-ahead generation forecasts (published ~18:00 D-1, Reg. 543/2013 Art. 14.1(d)).
    # Filter ids verified 2026-11-14: 125 + 123 + 3791 == 5097 ("wind + PV" forecast).
    "tso_da_gen_solar": 125,
    "tso_da_gen_wind_onshore": 123,
    "tso_da_gen_wind_offshore": 3791,
    # Published total of the three above; used only for the consistency check in the quality report.
    "tso_da_gen_wind_solar_total": 5097,
}

# SMARD region codes: DE-LU bidding zone, DE, and the four German TSO control areas.
REGIONS = ["DE-LU", "DE", "50Hertz", "Amprion", "TenneT", "TransnetBW"]
RESOLUTION_MINUTES = {"quarterhour": 15, "hour": 60}


@dataclass(frozen=True)
class SmardWeek:
    record: RawRecord
    rows: pl.DataFrame
    created_utc: datetime | None


def _get(client: httpx.Client, url: str) -> bytes:
    for attempt in range(4):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                raise FileNotFoundError(url)
        except httpx.TransportError:
            pass
        time.sleep(2**attempt)
    raise RuntimeError(f"SMARD request failed after retries: {url}")


def client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT})


def week_index(c: httpx.Client, metric: str, region: str, resolution: str = "quarterhour") -> list[int]:
    f = FILTERS[metric]
    data = json.loads(_get(c, f"{BASE}/{f}/{region}/index_{resolution}.json"))
    return sorted(data["timestamps"])


def parse_week(content: bytes, resolution: str) -> tuple[pl.DataFrame, datetime | None]:
    """Parse one weekly file into interval-start UTC rows with MW and MWh."""
    data = json.loads(content)
    res_min = RESOLUTION_MINUTES[resolution]
    series = data.get("series") or []
    created_ms = (data.get("meta_data") or {}).get("created")
    df = pl.DataFrame(
        {
            "timestamp_utc": [s[0] for s in series],
            "energy_mwh": [None if s[1] is None else float(s[1]) for s in series],
        },
        schema={"timestamp_utc": pl.Int64, "energy_mwh": pl.Float64},
    ).with_columns(
        pl.from_epoch("timestamp_utc", time_unit="ms").dt.replace_time_zone("UTC"),
        resolution_minutes=pl.lit(res_min, pl.Int64),
        value_mw=pl.col("energy_mwh") * (60.0 / res_min),
    )
    created = datetime.fromtimestamp(created_ms / 1000, timezone.utc) if created_ms else None
    return df, created


def fetch_week(
    c: httpx.Client, metric: str, region: str, week_ts: int, resolution: str = "quarterhour"
) -> SmardWeek:
    f = FILTERS[metric]
    url = f"{BASE}/{f}/{region}/{f}_{region}_{resolution}_{week_ts}.json"
    content = _get(c, url)
    rows, created = parse_week(content, resolution)
    rec = store_raw(
        content,
        source=SOURCE,
        dataset=metric,
        params={"filter": f, "region": region, "resolution": resolution, "week_ts": week_ts, "url": url},
        licence=LICENCE,
        suffix=".json",
        extra={"source_created_utc": created.isoformat() if created else None},
    )
    return SmardWeek(rec, rows, created)
