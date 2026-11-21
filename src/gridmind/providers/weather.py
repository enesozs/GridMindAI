"""Weather locations for DE-LU.

The weather values themselves come from Open-Meteo (see providers/openmeteo.py). This
module only defines where they are sampled and how locations are weighted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherPoint:
    location_id: str
    lat: float
    lon: float
    weight: float


# The largest German urban areas plus Luxembourg, weighted by APPROXIMATE urban-area
# population in millions (hand-entered, rounded). Load follows people, so these points
# and weights drive the population-weighted temperature used by the load model.
DE_LU_POINTS: list[WeatherPoint] = [
    WeatherPoint("berlin", 52.52, 13.40, 4.5),
    WeatherPoint("ruhr_essen", 51.46, 7.01, 5.0),
    WeatherPoint("hamburg", 53.55, 10.00, 3.3),
    WeatherPoint("munich", 48.14, 11.58, 2.9),
    WeatherPoint("cologne_duesseldorf", 51.04, 6.85, 3.6),
    WeatherPoint("frankfurt", 50.11, 8.68, 2.6),
    WeatherPoint("stuttgart", 48.78, 9.18, 2.8),
    WeatherPoint("leipzig_halle", 51.40, 12.20, 1.2),
    WeatherPoint("nuremberg", 49.45, 11.08, 1.3),
    WeatherPoint("hanover", 52.37, 9.73, 1.2),
    WeatherPoint("dresden", 51.05, 13.74, 0.8),
    WeatherPoint("bremen", 53.08, 8.80, 0.9),
    WeatherPoint("luxembourg", 49.61, 6.13, 0.4),
]


# Renewables sites (weights unused): where PV and wind capacity actually is, rather than where
# people live. Coordinates are representative locations in the main capacity regions
# (hand-picked, approximate), plus the North Sea and Baltic offshore clusters.
RENEWABLES_POINTS: list[WeatherPoint] = [
    WeatherPoint("pv_bavaria_south", 48.35, 11.75, 1.0),
    WeatherPoint("pv_lower_franconia", 49.80, 10.00, 1.0),
    WeatherPoint("pv_baden_wuerttemberg", 48.60, 9.40, 1.0),
    WeatherPoint("pv_nrw", 51.60, 7.60, 1.0),
    WeatherPoint("pv_brandenburg", 52.20, 13.60, 1.0),
    WeatherPoint("wind_schleswig_holstein", 54.45, 9.20, 1.0),
    WeatherPoint("wind_emsland", 53.15, 7.45, 1.0),
    WeatherPoint("wind_lower_saxony", 52.85, 9.60, 1.0),
    WeatherPoint("wind_mecklenburg", 53.75, 12.60, 1.0),
    WeatherPoint("wind_brandenburg", 52.70, 13.80, 1.0),
    WeatherPoint("wind_saxony_anhalt", 52.05, 11.60, 1.0),
    WeatherPoint("wind_east_nrw", 51.60, 8.70, 1.0),
    WeatherPoint("offshore_borkum", 53.95, 6.40, 1.0),
    WeatherPoint("offshore_helgoland", 54.25, 7.80, 1.0),
    WeatherPoint("offshore_outer_north_sea", 54.75, 6.30, 1.0),
    WeatherPoint("offshore_baltic", 54.75, 13.20, 1.0),
]
