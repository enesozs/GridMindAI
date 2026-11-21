"use client";

import { useMemo, useState } from "react";
import { DataCredits } from "@/components/Credits";
import { EChart, baseAxis, baseTooltip, useTokens, type Tokens } from "@/components/EChart";
import { ErrorState, Panel, Skeleton, Stat } from "@/components/ui";
import { fmtGW, fmtMW, useData } from "@/lib/data";

type SummaryRow = {
  source: string; label: string; mean_peak_reduction_mw: number; value_captured: number | null;
  days_peak_worse: number; residual_forecast_mae_mw: number; mean_throughput_mwh: number; non_optimal_solves: number;
};
type Storage = {
  generated_at: string;
  fleet: { power_mw: number; energy_mwh: number; round_trip_eff: number; soc_min_frac: number; soc_max_frac: number; soc_start_frac: number };
  period: [string, string];
  summary: [{ days_evaluated: number; days_skipped_incomplete: number }, ...SummaryRow[]];
  per_day: Record<string, (number | string | null)[]>;
  hourly: Record<string, (number | string | null)[]>;
};

const SOURCE_TOKEN: Record<string, keyof Tokens> = {
  perfect: "s3", tso: "tso", gridmind_load_tso_res: "s2", gridmind: "s1", naive_d7: "s5",
};
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit" });

export default function StorageLab() {
  const t = useTokens();
  const d = useData<Storage>("storage.json");
  const [source, setSource] = useState("gridmind_load_tso_res");
  const [dayIdx, setDayIdx] = useState<number | null>(null);
  const rows = useMemo(() => (d.data?.summary.slice(1) ?? []) as SummaryRow[], [d.data]);
  const meta = d.data?.summary[0] as { days_evaluated: number; days_skipped_incomplete: number } | undefined;
  const days = (d.data?.per_day.delivery_day ?? []) as string[];
  const di = dayIdx ?? Math.max(0, days.length - 1);
  const day = days[di];

  const dayData = useMemo(() => {
    if (!d.data || !day) return null;
    const h = d.data.hourly;
    const idx = (h.delivery_day as string[]).map((x, i) => (x === day ? i : -1)).filter((i) => i >= 0);
    const at = (k: string) => idx.map((i) => h[k]?.[i] as number | null);
    return { ts: idx.map((i) => Date.parse(h.valid_at_utc[i] as string)), residual: at("residual"), after: at(`after_${source}`),
             afterPerfect: at("after_perfect"), net: at(`net_${source}`), soc: at(`soc_${source}`), socPerfect: at("soc_perfect") };
  }, [d.data, day, source]);

  const dayStats = useMemo(() => {
    if (!d.data || !day) return null;
    const p = d.data.per_day;
    const i = (p.delivery_day as string[]).indexOf(day);
    return { before: p.peak_before_mw[i] as number, red: p[`${source}_reduction_mw`]?.[i] as number,
             redPerfect: p.perfect_reduction_mw[i] as number };
  }, [d.data, day, source]);

  const loadOption = useMemo(() => {
    if (!t || !dayData) return null;
    const z = (a: (number | null)[]) => dayData.ts.map((x, j) => [x, a[j]]);
    const line = { type: "line", step: "start", showSymbol: false };
    return {
      grid: { left: 56, right: 20, top: 56, bottom: 36 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number | null) => fmtGW(v, 2) },
      xAxis: { type: "time", ...baseAxis(t), splitLine: { show: false }, axisLabel: { color: t.muted, formatter: (v: number) => hourFmt.format(v) } },
      yAxis: { type: "value", scale: true, ...baseAxis(t), name: "GW", nameTextStyle: { color: t.muted },
               axisLabel: { color: t.muted, formatter: (v: number) => `${(v / 1000).toFixed(0)}` } },
      series: [
        { ...line, name: "Residual load (actual)", data: z(dayData.residual), lineStyle: { color: t.actual, width: 1.6 }, itemStyle: { color: t.actual } },
        { ...line, name: "With storage: perfect plan", data: z(dayData.afterPerfect), lineStyle: { color: t.s3, width: 1.4, type: "dashed" }, itemStyle: { color: t.s3 } },
        { ...line, name: `With storage: ${rows.find((r) => r.source === source)?.label ?? source}`, data: z(dayData.after),
          lineStyle: { color: t[SOURCE_TOKEN[source]], width: 2 }, itemStyle: { color: t[SOURCE_TOKEN[source]] } },
      ],
    };
  }, [t, dayData, source, rows]);

  const fleetOption = useMemo(() => {
    if (!t || !dayData || !d.data) return null;
    const f = d.data.fleet;
    return {
      grid: [{ left: 56, right: 20, top: 64, height: 100 }, { left: 56, right: 20, top: 208, bottom: 36 }],
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis" },
      xAxis: [
        { type: "time", gridIndex: 0, ...baseAxis(t), splitLine: { show: false }, axisLabel: { show: false } },
        { type: "time", gridIndex: 1, ...baseAxis(t), splitLine: { show: false }, axisLabel: { color: t.muted, formatter: (v: number) => hourFmt.format(v) } },
      ],
      yAxis: [
        { type: "value", gridIndex: 0, ...baseAxis(t), name: "MW (+ charge)", nameTextStyle: { color: t.muted, fontSize: 10 },
          min: -f.power_mw, max: f.power_mw, axisLabel: { color: t.muted, fontSize: 10 } },
        { type: "value", gridIndex: 1, ...baseAxis(t), name: "GWh stored", nameTextStyle: { color: t.muted, fontSize: 10 },
          min: 0, max: f.energy_mwh, axisLabel: { color: t.muted, formatter: (v: number) => `${(v / 1000).toFixed(0)}` } },
      ],
      series: [
        { type: "bar", name: "Charge (+) / discharge (−)", xAxisIndex: 0, yAxisIndex: 0, barCategoryGap: "20%",
          data: dayData.ts.map((x, j) => [x, dayData.net[j]]), itemStyle: { color: t[SOURCE_TOKEN[source]], borderRadius: 2 },
          tooltip: { valueFormatter: (v: number) => fmtMW(v) } },
        { type: "line", name: "State of charge", xAxisIndex: 1, yAxisIndex: 1, step: "end", showSymbol: false,
          data: dayData.ts.map((x, j) => [x, dayData.soc[j]]), lineStyle: { color: t[SOURCE_TOKEN[source]], width: 2 }, itemStyle: { color: t[SOURCE_TOKEN[source]] },
          markLine: { symbol: "none", silent: true, lineStyle: { color: t.muted, type: "dotted" }, label: { color: t.muted, fontSize: 10, formatter: "{b}", position: "insideEndTop" },
                      data: [{ yAxis: f.soc_min_frac * f.energy_mwh, name: "min" }, { yAxis: f.soc_max_frac * f.energy_mwh, name: "max" }] },
          tooltip: { valueFormatter: (v: number) => `${(v / 1000).toFixed(2)} GWh` } },
      ],
    };
  }, [t, dayData, d.data, source]);

  if (d.error) return <ErrorState message={d.error} onRetry={d.retry} />;
  const f = d.data?.fleet;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Storage Lab</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          What is a forecast worth when you act on it? A stylised storage fleet
          {f ? ` (${f.power_mw / 1000} GW / ${f.energy_mwh / 1000} GWh, ${Math.round(f.round_trip_eff * 100)}% round-trip efficiency)` : ""} is
          scheduled the day before to flatten the peak of <b>residual load</b> (load minus wind and solar, the demand that
          other plants must cover). The schedule is planned on a forecast and then applied to what actually happened.
          Value is measured as peak reduction, not money: this project uses no price data.
        </p>
      </div>

      <Panel title="How much of the perfect-foresight value each forecast captures"
             subtitle={d.data ? `Test year ${d.data.period[0]} → ${d.data.period[1]} · ${meta?.days_evaluated} days (${meta?.days_skipped_incomplete} skipped: incomplete data)` : "…"}
             footer={<>Each day is solved as a linear program (HiGHS). The TSO renewables forecasts are published ~18:00 the day before, later than GridMind&apos;s 10:00 issue time. <DataCredits /></>}>
        {!rows.length ? <Skeleton height={200} /> : (
          <div className="overflow-x-auto">
            <table className="num w-full min-w-[680px] text-[13px]">
              <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border">
                <th className="py-1.5 pr-3">Plan made with</th><th className="pr-3">Mean peak reduction</th><th className="pr-3">Share of perfect</th>
                <th className="pr-3">Days peak got worse</th><th className="pr-3">Residual forecast MAE</th><th>Solver</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.source} onClick={() => r.source !== "perfect" && setSource(r.source)}
                      className={`border-b border-border ${r.source === source ? "font-semibold" : ""} ${r.source !== "perfect" ? "cursor-pointer hover:bg-surface-2" : "text-muted"}`}>
                    <td className="py-1.5 pr-3">
                      <span className="mr-2 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: t ? t[SOURCE_TOKEN[r.source]] : undefined }} />
                      {r.label}
                    </td>
                    <td className="pr-3">{fmtMW(r.mean_peak_reduction_mw)}</td>
                    <td className="pr-3">{r.value_captured == null ? "—" : `${Math.round(r.value_captured * 100)}%`}</td>
                    <td className="pr-3">{r.days_peak_worse}</td>
                    <td className="pr-3">{r.source === "perfect" ? "—" : fmtMW(r.residual_forecast_mae_mw)}</td>
                    <td>{r.non_optimal_solves === 0 ? "✓ all optimal" : `⚠ ${r.non_optimal_solves} not optimal`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
        <label className="flex flex-1 items-center gap-3 text-[13px] text-ink-2">
          <span className="num whitespace-nowrap font-medium text-ink">Day {day ?? "…"}</span>
          <input type="range" min={0} max={Math.max(0, days.length - 1)} value={di} onChange={(e) => setDayIdx(Number(e.target.value))}
                 className="w-full accent-[var(--accent)]" aria-label="Select day" />
        </label>
        <label className="flex items-center gap-2 text-[13px] text-ink-2">Plan made with
          <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1 text-ink">
            {rows.filter((r) => r.source !== "perfect").map((r) => <option key={r.source} value={r.source}>{r.label}</option>)}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat label="Peak residual load without storage" value={fmtGW(dayStats?.before, 1)} />
        <Stat label="Peak reduction with this plan" value={fmtMW(dayStats?.red)}
              note={dayStats && dayStats.red < -1 ? "the plan made the real peak worse" : undefined} />
        <Stat label="Peak reduction with a perfect plan" value={fmtMW(dayStats?.redPerfect)} note="upper bound" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Residual load, with and without storage" subtitle="GW, local time. Flatter peaks = less stress on the system.">
          {loadOption ? <EChart option={loadOption} height={320} ariaLabel={`Residual load with storage on ${day}`} /> : <Skeleton height={320} />}
        </Panel>
        <Panel title="What the fleet did" subtitle="Hourly charge/discharge (MW) and stored energy (GWh) for the selected plan.">
          {fleetOption ? <EChart option={fleetOption} height={320} ariaLabel={`Storage dispatch and state of charge on ${day}`} /> : <Skeleton height={320} />}
        </Panel>
      </div>
    </div>
  );
}
