"""Open-Meteo Previous Runs API: archived forecasts at a FIXED LEAD of 48 h.

Licence (checked 2026-11-14, open-meteo.com/en/terms + /en/licence): data CC BY 4.0
("Weather data by Open-Meteo.com"); the free API is for NON-COMMERCIAL use only, under
10,000 calls/day; GridMind is a non-commercial project. Underlying model: NOAA GFS.

Semantics (open-meteo.com/en/docs/previous-runs-api): `<var>_previous_day2` is "the value
predicted 48 hours before valid time". For any valid hour h of delivery day D, the source
run started at or before h - 48 h (no later than about D-2 23:00 UTC), and it was published
hours before our issue time D-1 10:00 Europe/Berlin. So it is point-in-time safe without
per-run bookkeeping. Coverage (verified 2026-11-14): temperature_2m from 2021; radiation,
cloud cover and wind from early 2024 (null before).

A fixed-lead archive avoids per-run bookkeeping and needs only a handful of point
requests, instead of downloading gridded model runs.
"""

from __future__ import annotations

import time
from datetime import date

import httpx
import polars as pl

from gridmind.providers.weather import DE_LU_POINTS, RENEWABLES_POINTS, WeatherPoint
from gridmind.storage import store_raw

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
SOURCE = "open-meteo"
LICENCE = "CC-BY-4.0 'Weather data by Open-Meteo.com' (free API: non-commercial only)"
MODEL = "gfs_seamless"
LEAD_DAYS = 2
VARIABLES = {  # open-meteo name -> canonical column
    "temperature_2m": "temperature_2m",
    "shortwave_radiation": "downward_short_wave_radiation_flux_surface",
    "cloud_cover": "total_cloud_cover_atmosphere",
    "wind_speed_10m": "wind_speed_10m",
    "wind_speed_100m": "wind_speed_100m",
}
DATASET = f"openmeteo-{MODEL}-previous_day{LEAD_DAYS}"


def _get(client: httpx.Client, params: dict) -> bytes:
    for attempt in range(5):
        try:
            r = client.get(URL, params=params, timeout=120)
            if r.status_code == 200:
                return r.content
            if r.status_code == 429:
                time.sleep(60)
                continue
            raise RuntimeError(f"Open-Meteo HTTP {r.status_code}: {r.text[:200]}")
        except httpx.TransportError:
            time.sleep(2**attempt)
    raise RuntimeError("Open-Meteo request failed after retries")


def fetch_point(client: httpx.Client, p: WeatherPoint, variables: list[str], start: date, end: date) -> pl.DataFrame:
    hourly = [f"{v}_previous_day{LEAD_DAYS}" for v in variables]
    params = {"latitude": p.lat, "longitude": p.lon, "hourly": ",".join(hourly), "models": MODEL,
              "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "GMT"}
    content = _get(client, params)
    store_raw(content, source=SOURCE, dataset=DATASET, params={**params, "location": p.location_id},
              licence=LICENCE, suffix=".json")
    import json

    h = json.loads(content)["hourly"]
    df = pl.DataFrame({"valid_at_utc": h["time"], **{VARIABLES[v]: h[f"{v}_previous_day{LEAD_DAYS}"]
                                                      for v in variables}})
    return df.with_columns(
        pl.col("valid_at_utc").str.to_datetime("%Y-%m-%dT%H:%M").dt.replace_time_zone("UTC"),
        *[pl.col(VARIABLES[v]).cast(pl.Float64) for v in variables],
        location=pl.lit(p.location_id),
    )


def fetch_all(start_t2m: date, start_other: date, end: date, pause_s: float = 1.0, log=print) -> pl.DataFrame:
    """All 13 DE-LU points: temperature from `start_t2m`, other variables from `start_other`."""
    frames = []
    with httpx.Client(headers={"User-Agent": "GridMindAI research pipeline (non-commercial)"}) as c:
        for p in DE_LU_POINTS:
            t = fetch_point(c, p, ["temperature_2m"], start_t2m, end)
            time.sleep(pause_s)
            o = fetch_point(c, p, ["shortwave_radiation", "cloud_cover", "wind_speed_10m"], start_other, end)
            time.sleep(pause_s)
            frames.append(t.join(o, on=["valid_at_utc", "location"], how="left"))
            log(f"  {p.location_id}: {t.height} hours")
    df = pl.concat(frames).sort("location", "valid_at_utc")
    return df.with_columns(
        weather_model=pl.lit(DATASET),
        forecast_lead_hours=pl.lit(24.0 * LEAD_DAYS),
        # Nominal run time (valid - 48 h). The actual run started at or before this.
        weather_model_run=pl.col("valid_at_utc") - pl.duration(days=LEAD_DAYS),
    )


RENEWABLES_VARIABLES = ["shortwave_radiation", "cloud_cover", "wind_speed_100m", "temperature_2m"]


def fetch_renewables_points(start: date, end: date, pause_s: float = 1.0, log=print) -> pl.DataFrame:
    """Solar-, wind- and offshore-site points (see providers/weather.py), 48-h-lead forecasts.

    Wind is at 100 m (closer to turbine hub height than 10 m). Note: Open-Meteo reports
    wind speed in km/h; trees are unaffected by the unit.
    """
    frames = []
    with httpx.Client(headers={"User-Agent": "GridMindAI research pipeline (non-commercial)"}) as c:
        for p in RENEWABLES_POINTS:
            frames.append(fetch_point(c, p, RENEWABLES_VARIABLES, start, end))
            time.sleep(pause_s)
            log(f"  {p.location_id}: {frames[-1].height} hours")
    return pl.concat(frames).sort("location", "valid_at_utc").with_columns(
        weather_model=pl.lit(DATASET),
        forecast_lead_hours=pl.lit(24.0 * LEAD_DAYS),
        weather_model_run=pl.col("valid_at_utc") - pl.duration(days=LEAD_DAYS),
    )
