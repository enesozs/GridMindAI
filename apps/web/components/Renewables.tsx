"use client";

import { useMemo, useState } from "react";
import { DataCredits } from "@/components/Credits";
import { EChart, baseAxis, baseTooltip, useTokens } from "@/components/EChart";
import { ErrorState, Panel, Skeleton } from "@/components/ui";
import { MODEL_LABEL, fmtGW, fmtMW, fmtPct, useData } from "@/lib/data";

type Row = { model: string; mae_mw: number; rmse_mw: number; bias_mw: number; skill_vs_tso: number; coverage_90?: number | null; coverage_50?: number | null };
type PeriodRes = { n_hours: number; from: string; to: string; leaderboard: Row[]; dm: { dm_stat: number | null; p_value: number | null; n_days: number }[] };
type Hourly = { delivery_day: string[]; valid_at_utc: string[]; y: (number | null)[]; tso_forecast: (number | null)[]; q05: (number | null)[]; q25: (number | null)[]; q50: (number | null)[]; q75: (number | null)[]; q95: (number | null)[] };
type Renew = { generated_at: string; note: string; results: Record<string, { validation: PeriodRes; test: PeriodRes }>; replay: Record<string, Hourly> };

const TECH: Record<string, string> = { solar: "Solar PV", wind_onshore: "Wind onshore", wind_offshore: "Wind offshore" };
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit" });

export default function RenewablesView() {
  const t = useTokens();
  const d = useData<Renew>("renewables.json");
  const [tech, setTech] = useState("solar");
  const [dayIdx, setDayIdx] = useState<number | null>(null);
  const rp = d.data?.replay[tech];
  const days = useMemo(() => (rp ? [...new Set(rp.delivery_day)] : []), [rp]);
  const di = dayIdx ?? Math.max(0, days.length - 1);
  const day = days[di];

  const option = useMemo(() => {
    if (!t || !rp || !day) return null;
    const idx = rp.delivery_day.map((x, i) => (x === day ? i : -1)).filter((i) => i >= 0);
    const ts = idx.map((i) => Date.parse(rp.valid_at_utc[i]));
    const col = (k: keyof Hourly) => idx.map((i, j) => [ts[j], rp[k][i] as number | null]);
    const band = (a: keyof Hourly, b: keyof Hourly) =>
      idx.map((i, j) => [ts[j], rp[b][i] != null && rp[a][i] != null ? (rp[b][i] as number) - (rp[a][i] as number) : null]);
    const line = { type: "line", step: "start", showSymbol: false };
    return {
      grid: { left: 56, right: 20, top: 56, bottom: 40 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8,
                data: ["GridMind median", "90% interval", "TSO day-ahead forecast", "Actual"] },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number | null) => fmtGW(v, 2) },
      xAxis: { type: "time", ...baseAxis(t), splitLine: { show: false }, axisLabel: { color: t.muted, formatter: (v: number) => hourFmt.format(v) } },
      yAxis: { type: "value", ...baseAxis(t), name: "GW", nameTextStyle: { color: t.muted }, min: 0,
               axisLabel: { color: t.muted, formatter: (v: number) => `${(v / 1000).toFixed(0)}` } },
      series: [
        { ...line, name: "lo", data: col("q05"), stack: "b", lineStyle: { opacity: 0 }, tooltip: { show: false } },
        { ...line, name: "90% interval", data: band("q05", "q95"), stack: "b", lineStyle: { opacity: 0 }, areaStyle: { color: t.band }, itemStyle: { color: t.band } },
        { ...line, name: "GridMind median", data: col("q50"), lineStyle: { color: t.s1, width: 2 }, itemStyle: { color: t.s1 } },
        { ...line, name: "TSO day-ahead forecast", data: col("tso_forecast"), lineStyle: { color: t.tso, width: 1.5, type: "dashed" }, itemStyle: { color: t.tso } },
        { ...line, name: "Actual", data: col("y"), lineStyle: { color: t.actual, width: 1.6 }, itemStyle: { color: t.actual }, z: 5 },
      ],
    };
  }, [t, rp, day]);

  if (d.error) return <ErrorState message={d.error} onRetry={d.retry} />;
  const res = d.data?.results[tech];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Renewables</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          Day-ahead forecasts of solar and wind generation for Germany–Luxembourg, issued at the same 10:00 D-1 deadline as the
          load forecast, using the 48-hour-lead weather forecast at 13 locations. The benchmark is the TSOs&apos; own day-ahead
          generation forecast, which is published around <b>18:00</b>, eight hours later, with fresher weather.
        </p>
        <p className="mt-2 max-w-3xl rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-ink-2">
          <b className="text-ink">Result: the TSO forecasts are still better</b> for all three technologies, but
          weather taken at wind-farm and offshore sites at 100 m height cut GridMind&apos;s wind errors by about a quarter
          (onshore) to a third (offshore). For solar, the site points did not help on validation data, so the original
          model is kept. The intervals stay calibrated. Details: docs/reports/renewables_benchmark.md.
        </p>
      </div>
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Technology">
        {Object.entries(TECH).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tech === k} onClick={() => { setTech(k); setDayIdx(null); }}
                  className={`rounded-md border border-border px-3 py-1 text-[13px] ${tech === k ? "bg-surface-2 font-medium text-ink" : "text-ink-2"}`}>
            {label}
          </button>
        ))}
      </div>

      <Panel title={`${TECH[tech]}: test year (frozen holdout)`}
             subtitle={res ? `${res.test.from} → ${res.test.to} · ${res.test.n_hours.toLocaleString("en-GB")} scored hours · validation: ${res.validation.from} → ${res.validation.to}` : "…"}
             footer="MAE/RMSE/bias in MW of hourly generation. Skill = 1 − MAE / MAE(TSO forecast). Training starts Feb 2024, the first month with archived radiation and wind forecasts.">
        {!res ? <Skeleton height={180} /> : (
          <div className="overflow-x-auto">
            <table className="num w-full min-w-[640px] text-[13px]">
              <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border">
                <th className="py-1.5 pr-3">Model</th><th className="pr-3">MAE test</th><th className="pr-3">RMSE</th><th className="pr-3">Bias</th>
                <th className="pr-3">Skill vs TSO</th><th className="pr-3">Cov. 90%</th><th>MAE validation</th></tr></thead>
              <tbody>
                {res.test.leaderboard.map((r) => {
                  const v = res.validation.leaderboard.find((x) => x.model === r.model);
                  return (
                    <tr key={r.model} className={`border-b border-border ${r.model === "gbm_weather" ? "font-semibold" : ""}`}>
                      <td className="py-1.5 pr-3">{r.model === "tso_official" ? "TSO day-ahead forecast (18:00)" : MODEL_LABEL[r.model] ?? r.model}</td>
                      <td className="pr-3">{fmtMW(r.mae_mw)}</td><td className="pr-3">{fmtMW(r.rmse_mw)}</td>
                      <td className="pr-3">{r.bias_mw > 0 ? "+" : ""}{fmtMW(r.bias_mw)}</td>
                      <td className="pr-3" style={{ color: r.skill_vs_tso > 0.0005 ? "var(--good-text)" : r.skill_vs_tso < -0.0005 ? "var(--critical)" : undefined }}>
                        {r.model === "tso_official" ? "—" : `${r.skill_vs_tso > 0 ? "▲ " : r.skill_vs_tso < 0 ? "▼ " : ""}${fmtPct(r.skill_vs_tso, 1, true)}`}</td>
                      <td className="pr-3">{r.coverage_90 == null ? "—" : r.coverage_90.toFixed(3)}</td>
                      <td>{fmtMW(v?.mae_mw)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Replay a test-year day" subtitle={<span className="num">Delivery day {day ?? "…"}</span>}
             footer={<DataCredits />}>
        {days.length > 0 && (
          <input type="range" min={0} max={days.length - 1} value={di} onChange={(e) => setDayIdx(Number(e.target.value))}
                 className="mb-3 w-full accent-[var(--accent)]" aria-label="Select delivery day" />
        )}
        {option ? <EChart option={option} height={340} ariaLabel={`${TECH[tech]} forecast for ${day}`} /> : <Skeleton height={340} />}
      </Panel>
    </div>
  );
}
