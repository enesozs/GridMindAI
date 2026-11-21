"use client";

import { useMemo, useState } from "react";
import { DataCredits } from "@/components/Credits";
import { EChart, baseAxis, baseTooltip, useTokens } from "@/components/EChart";
import { Panel, Skeleton } from "@/components/ui";
import { ZONE_LABEL, fmtGW, fmtMW, fmtPct, useData } from "@/lib/data";

type CA = {
  generated_at: string;
  chosen_method: string;
  period: string;
  incoherence: { base_mae_mw: number; tso_mae_mw: number };
  methods: Record<string, number>;
  series: Record<string, { mae_gridmind: number; mae_tso: number; skill_vs_tso: number; mae_base: number }>;
  hourly: Record<string, (number | string | null)[]>;
};

const ZONES = ["DE", "DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"];
const METHOD_LABEL: Record<string, string> = { base: "no reconciliation", bottom_up: "bottom-up", ols: "OLS", mint_shrink: "MinT (shrinkage)" };
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit" });

export default function ControlAreaForecasts() {
  const t = useTokens();
  const d = useData<CA>("control_areas.json");
  const [zone, setZone] = useState("DE_TENNET");
  const [dayIdx, setDayIdx] = useState<number | null>(null);
  const days = useMemo(() => (d.data ? [...new Set(d.data.hourly.delivery_day as string[])] : []), [d.data]);
  const di = dayIdx ?? Math.max(0, days.length - 1);
  const day = days[di];

  const option = useMemo(() => {
    if (!t || !d.data || !day) return null;
    const h = d.data.hourly;
    const idx = (h.delivery_day as string[]).map((x, i) => (x === day ? i : -1)).filter((i) => i >= 0);
    const z = (k: string) => idx.map((i) => [Date.parse(h.valid_at_utc[i] as string), h[k][i] as number | null]);
    const line = { type: "line", step: "start", showSymbol: false };
    return {
      grid: { left: 56, right: 20, top: 56, bottom: 36 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number | null) => fmtGW(v, 2) },
      xAxis: { type: "time", ...baseAxis(t), splitLine: { show: false }, axisLabel: { color: t.muted, formatter: (v: number) => hourFmt.format(v) } },
      yAxis: { type: "value", scale: true, ...baseAxis(t), name: "GW", nameTextStyle: { color: t.muted },
               axisLabel: { color: t.muted, formatter: (v: number) => `${(v / 1000).toFixed(0)}` } },
      series: [
        { ...line, name: "GridMind (reconciled)", data: z(`gm_${zone}`), lineStyle: { color: t.s1, width: 2 }, itemStyle: { color: t.s1 } },
        { ...line, name: "TSO day-ahead forecast", data: z(`tso_${zone}`), lineStyle: { color: t.tso, width: 1.5, type: "dashed" }, itemStyle: { color: t.tso } },
        { ...line, name: "Actual", data: z(`y_${zone}`), lineStyle: { color: t.actual, width: 1.6 }, itemStyle: { color: t.actual }, z: 5 },
      ],
    };
  }, [t, d.data, day, zone]);

  if (d.error) return null; // optional module: the Atlas stays usable without it
  const c = d.data;

  return (
    <Panel title="Control-area forecasts"
           subtitle={c ? `Day-ahead load for each TSO area and Germany, made to add up (${METHOD_LABEL[c.chosen_method]}, chosen on validation data). Test year, MAE in MW.` : "…"}
           footer={c ? <>{`Independent forecasts disagreed with their own total by ${fmtMW(c.incoherence.base_mae_mw)} on average; the TSOs' published forecasts by ${fmtMW(c.incoherence.tso_mae_mw)}. Reconciled forecasts add up exactly. Weather per area uses the population points inside it. `}<DataCredits /></> : undefined}>
      {!c ? <Skeleton height={240} /> : (
        <>
          <div className="overflow-x-auto">
            <table className="num w-full min-w-[620px] text-[13px]">
              <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border">
                <th className="py-1.5 pr-3">Series</th><th className="pr-3">TSO forecast</th><th className="pr-3">GridMind, independent</th>
                <th className="pr-3">GridMind, reconciled</th><th>Skill vs TSO</th></tr></thead>
              <tbody>
                {ZONES.map((zz) => {
                  const s = c.series[zz];
                  return (
                    <tr key={zz} onClick={() => setZone(zz)} className={`cursor-pointer border-b border-border hover:bg-surface-2 ${zz === zone ? "font-semibold" : ""}`}>
                      <td className="py-1.5 pr-3">{ZONE_LABEL[zz]}</td><td className="pr-3">{fmtMW(s.mae_tso)}</td>
                      <td className="pr-3">{fmtMW(s.mae_base)}</td><td className="pr-3">{fmtMW(s.mae_gridmind)}</td>
                      <td style={{ color: s.skill_vs_tso > 0.0005 ? "var(--good-text)" : s.skill_vs_tso < -0.0005 ? "var(--critical)" : undefined }}>
                        {s.skill_vs_tso > 0 ? "▲ " : s.skill_vs_tso < 0 ? "▼ " : ""}{fmtPct(s.skill_vs_tso, 1, true)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-[13px] text-ink-2">
            <label className="flex items-center gap-2">Series
              <select value={zone} onChange={(e) => setZone(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1 text-ink" aria-label="Control area">
                {ZONES.map((zz) => <option key={zz} value={zz}>{ZONE_LABEL[zz]}</option>)}
              </select>
            </label>
            <label className="flex flex-1 items-center gap-3">
              <span className="num whitespace-nowrap font-medium text-ink">Day {day}</span>
              <input type="range" min={0} max={Math.max(0, days.length - 1)} value={di} onChange={(e) => setDayIdx(Number(e.target.value))}
                     className="w-full accent-[var(--accent)]" aria-label="Select delivery day for control-area replay" />
            </label>
          </div>
          <div className="mt-2">
            {option ? <EChart option={option} height={300} ariaLabel={`${ZONE_LABEL[zone]} day-ahead load forecast for ${day}`} /> : <Skeleton height={300} />}
          </div>
        </>
      )}
    </Panel>
  );
}
