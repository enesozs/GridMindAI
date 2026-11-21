# Data Contract

## Forecast definition

A forecast is `(zone, issue_time, valid_time, horizon, model_version)`.

- **Zone:** `DE_LU` (EIC 10Y1001A1001A82H). Germany kept the single zone in its Dec 2025 bidding-zone action plan. Any future split is a new zone id, never a silent change to `DE_LU`.
- **Target:** hourly mean actual total load in **MW** for each hour of delivery day D (23/24/25 hours, local Europe/Berlin day). It is the mean of the four quarter-hour values. An hour with any missing quarter-hour is null and flagged, and excluded from scoring.
- **Issue time:** **D-1 10:00 Europe/Berlin**, the TSO day-ahead forecast publication deadline. Code: `IssueRule.issue_time`.
- **Horizon:** 14–38 hours ahead (from the issue time to each hour of D).

## Information allowed at issue time

| Input | Rule | Code |
|---|---|---|
| Actual load | Intervals ending ≤ issue_time − 2 h (publication lag), so up to 07:00/08:00 local on D-1 | `IssueRule.last_known_load_end` |
| Weather forecast | **Fixed 48-h-lead GFS forecast** for each valid hour (Open-Meteo `_previous_day2`); nominal run = valid − 48 h, and nominal run + 6 h ≤ issue_time is asserted. | `weather_features_fixed_lead`, `assert_point_in_time` |
| Calendar / holidays | Known in advance. Allowed. | — |
| TSO forecast | **Benchmark only, never a feature** | — |
| Hindsight weather (lead-0 values) | **Never a feature**; only in the labelled "oracle weather" ablation | — |

## Canonical conventions

- `timestamp_utc` = interval **start**, timezone-aware UTC; intervals are half-open.
- Power in MW (mean over the interval). Energy in MWh. SMARD raw values are MWh per interval and are converted with `MW = MWh × 60 / resolution_minutes`.
- Resolution is stored per row (`resolution_minutes`). Hourly aggregation uses the mean and requires full coverage (`to_hourly_mean_mw`).
- Raw responses are immutable and content-addressed, recorded in `data/raw/manifest.jsonl` with query params (no secrets), licence and retrieval time.
- Observed actuals and forecast vintages are stored in separate tables.

## Known limitations (accepted)

1. **Actual-load revisions:** SMARD history is the latest revised vintage, not what was published at the time. Lag features in the backtest are therefore slightly optimistic. The live track record stores forecasts made with as-of data and measures this gap.
2. **TSO forecast publication time is assumed**, not observed.
3. **Weather publication lag is an assumption** (6 h after the nominal run time). With a 48-h lead the margin before the issue time is at least 3 h for every hour of D.
4. **Spatial weighting:** 13 points with hand-entered approximate population weights. A gridded-population replacement (e.g. GHSL, CC BY 4.0) is deferred; it needs its own licence check first.

## Window (frozen)

- **Data:** 2021-05-01 → latest complete day. Weather temperature from 2021-05; radiation, cloud and wind from 2024-01-20 (missing before).
- **Model development** (rolling-origin validation): 2021-05-01 → 2025-10-31.
- **Frozen test year:** **2025-11-01 → 2026-10-31**. It covers a full winter and summer, is never used for tuning, and is evaluated once per model version.

## DST test design

Spring-forward (23 h) and fall-back (25 h) days are covered by unit tests on delivery-day bounds, issue times, quarter-hour → hour aggregation and the feature builder, plus real SMARD and Open-Meteo fixtures for 2025-03-30.
