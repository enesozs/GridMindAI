"use client";

import { useEffect, useState } from "react";

export type Attribution = { source: string; licence: string; url: string; used_for: string };

export type Atlas = {
  generated_at: string;
  unit: string;
  data_end_utc: string;
  regions: Record<string, { date: string[]; load_mw: (number | null)[]; anomaly: (number | null)[] }>;
  carpet: { zone: string; dates: string[]; hours: number[]; load_mw: (number | null)[][] };
  generation_mix: {
    zone: string;
    dates: string[];
    series: Record<string, (number | null)[]>;
    excluded_no_data_in_window?: string[];
  };
  attribution: Attribution[];
};

export type Replay = {
  generated_at: string;
  model: string;
  unit: string;
  period: string;
  issue_rule: string;
  days: string[];
  day_scores: Record<string, { n: number; mae_gridmind: number | null; mae_tso: number | null; coverage_90: number | null }>;
  hourly: {
    delivery_day: string[];
    issue_time_utc: string[];
    valid_at_utc: string[];
    y: (number | null)[];
    tso_forecast: (number | null)[];
    q05: (number | null)[];
    q25: (number | null)[];
    q50: (number | null)[];
    q75: (number | null)[];
    q95: (number | null)[];
  };
};

export type LeaderRow = {
  model: string;
  label: string;
  mae_mw: number;
  rmse_mw: number;
  bias_mw: number;
  mape_pct: number;
  peak_mae_mw: number;
  skill_vs_tso: number;
  pinball_mean_mw?: number | null;
  coverage_50?: number | null;
  coverage_90?: number | null;
  width_90_mw?: number | null;
};

export type PeriodResult = {
  run_id: string;
  from: string;
  to: string;
  n_hours: number;
  leaderboard: LeaderRow[];
  dm: { model: string; vs: string; dm_stat: number | null; p_value: number | null; n_days: number }[];
  by_hour: { model: string; local_hour: number; mae: number }[];
  by_month: { model: string; month: string; mae: number }[];
  by_temp: { model: string; temp_bin: string; mae: number; hours: number }[];
};

export type Leaderboard = { generated_at: string; validation?: PeriodResult; test?: PeriodResult };

export type TrackDay = {
  delivery_day: string;
  issued_at_utc: string;
  on_time: boolean;
  weather_model_run: string;
  hours: number;
  scored: number;
  complete: boolean;
  mae_gridmind: number | null;
  mae_tso: number | null;
  coverage_90: number | null;
};

export type TrackRecord = {
  generated_at: string;
  status: "not_started" | "running";
  summary?: { days_issued: number; days_scored_on_time: number; mae_gridmind: number | null; mae_tso: number | null; coverage_90: number | null };
  days: TrackDay[];
  hourly: null | {
    delivery_day: string[];
    valid_at_utc: string[];
    q05: (number | null)[];
    q50: (number | null)[];
    q95: (number | null)[];
    y: (number | null)[];
    tso_forecast: (number | null)[];
  };
};

export type Meta = { generated_at: string; attribution: Attribution[]; zone: string; timezone: string };

type State<T> = { data: T | null; error: string | null; loading: boolean };

export function useData<T>(name: string): State<T> & { retry: () => void } {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetch(`/data/${name}`, { cache: "no-cache" })
      .then((r) => {
        if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => !cancelled && setState({ data: d as T, error: null, loading: false }))
      .catch((e: Error) => !cancelled && setState({ data: null, error: e.message, loading: false }));
    return () => {
      cancelled = true;
    };
  }, [name, attempt]);
  return {
    ...state,
    retry: () => {
      setState({ data: null, error: null, loading: true });
      setAttempt((a) => a + 1);
    },
  };
}

export const ZONE_LABEL: Record<string, string> = {
  DE_LU: "Germany–Luxembourg",
  DE: "Germany",
  DE_50HZ: "50Hertz",
  DE_AMPRION: "Amprion",
  DE_TENNET: "TenneT",
  DE_TRANSNETBW: "TransnetBW",
};

export const MODEL_LABEL: Record<string, string> = {
  tso_official: "TSO official forecast",
  gbm_weather: "GridMind GBM + weather",
  gbm_v1: "GridMind v1 (population-point weather)",
  gbm_no_weather: "GBM, no weather",
  gbm_oracle_weather: "GBM + hindsight weather (oracle)",
  ridge_calendar_lags: "Ridge, calendar + lags",
  naive_d7: "Naive: same hour last week",
  naive_d2: "Naive: same hour D-2",
  naive_holiday_adjusted: "Naive, holiday-adjusted",
};

export const fmtGW = (mw: number | null | undefined, digits = 1) =>
  mw == null ? "—" : `${(mw / 1000).toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits })} GW`;
export const fmtMW = (mw: number | null | undefined) =>
  mw == null ? "—" : `${Math.round(mw).toLocaleString("en-GB")} MW`;
export const fmtPct = (x: number | null | undefined, digits = 1, signed = false) =>
  x == null ? "—" : `${signed && x > 0 ? "+" : ""}${(x * 100).toFixed(digits).replace("-", "−")}%`;
