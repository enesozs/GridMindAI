# Test fixtures

Small real-data extracts, redistributed under their licences:

| File | Source | Licence / attribution |
|---|---|---|
| `smard_*_DE-LU_2025-03-30_31.csv` | SMARD chart_data, DE-LU, quarter-hour (spring DST day + next day) | CC BY 4.0 — "Bundesnetzagentur \| SMARD.de" (data originally from ENTSO-E) |
| `openmeteo_previous_day2_DE-LU_2025-03-30_31.csv` | Open-Meteo Previous Runs API (GFS, forecast made 48 h before valid time), 13 DE-LU points | CC BY 4.0 — "Weather data by Open-Meteo.com" |

Values are as retrieved on 2026-11-14 (`energy_mwh` is SMARD's raw energy per interval; `value_mw` is derived).
Synthetic fixtures live inline in the unit tests and are labelled SYNTHETIC there.

Licences: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Sources: [SMARD](https://www.smard.de) and [Open-Meteo](https://open-meteo.com/) ("Weather data by Open-Meteo.com"). Changes: rows filtered to the two days shown; `value_mw` derived from SMARD's `energy_mwh`; weather columns renamed to the project's canonical names.
