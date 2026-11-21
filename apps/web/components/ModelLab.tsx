"use client";

import { useMemo, useState } from "react";
import { EChart, baseAxis, baseTooltip, useTokens, type Tokens } from "@/components/EChart";
import { ErrorState, Panel, Skeleton } from "@/components/ui";
import { type Leaderboard, MODEL_LABEL, fmtMW, fmtPct, useData } from "@/lib/data";

const SERIES: { model: string; token: keyof Tokens; dashed?: boolean }[] = [
  { model: "gbm_weather", token: "s1" },
  { model: "tso_official", token: "tso", dashed: true },
  { model: "gbm_no_weather", token: "s2" },
  { model: "naive_d7", token: "s3" },
];

export default function ModelLab() {
  const t = useTokens();
  const lb = useData<Leaderboard>("leaderboard.json");
  const [period, setPeriod] = useState<"test" | "validation">("test");
  const res = lb.data?.[period];

  const hourOption = useMemo(() => {
    if (!t || !res) return null;
    return {
      grid: { left: 56, right: 16, top: 60, bottom: 36 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number) => fmtMW(v) },
      xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}h`), ...baseAxis(t), splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis(t), name: "MAE (MW)", nameTextStyle: { color: t.muted } },
      series: SERIES.filter((s) => res.by_hour.some((r) => r.model === s.model)).map((s) => {
        const pts = Array.from({ length: 24 }, (_, h) => res.by_hour.find((r) => r.model === s.model && r.local_hour === h)?.mae ?? null);
        return { type: "line", name: MODEL_LABEL[s.model], data: pts, showSymbol: false, lineStyle: { width: 2, color: t[s.token], type: s.dashed ? "dashed" : "solid" }, itemStyle: { color: t[s.token] } };
      }),
    };
  }, [t, res]);

  const monthOption = useMemo(() => {
    if (!t || !res) return null;
    const months = [...new Set(res.by_month.map((r) => r.month))].sort();
    return {
      grid: { left: 56, right: 16, top: 60, bottom: 48 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number) => fmtMW(v) },
      xAxis: { type: "category", data: months, ...baseAxis(t), splitLine: { show: false }, axisLabel: { color: t.muted, rotate: 45, fontSize: 10 } },
      yAxis: { type: "value", ...baseAxis(t), name: "MAE (MW)", nameTextStyle: { color: t.muted } },
      series: SERIES.slice(0, 2).map((s) => ({
        type: "bar", name: MODEL_LABEL[s.model], barGap: "10%", barMaxWidth: 14,
        data: months.map((m) => res.by_month.find((r) => r.model === s.model && r.month === m)?.mae ?? null),
        itemStyle: { color: t[s.token], borderRadius: [4, 4, 0, 0] },
      })),
    };
  }, [t, res]);

  if (lb.error) return <ErrorState message={lb.error} onRetry={lb.retry} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Model Laboratory</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          Every model is scored on the same hours, against the TSOs&apos; official day-ahead forecast. The{" "}
          <b>test year</b> was evaluated once, with model settings fixed beforehand; the <b>validation year</b> is where
          development happened. Skill = 1 − MAE / MAE(TSO); positive means better than the TSO forecast.
        </p>
      </div>
      <div className="flex gap-2" role="tablist" aria-label="Evaluation period">
        {(["test", "validation"] as const).map((p) => (
          <button key={p} role="tab" aria-selected={period === p} onClick={() => setPeriod(p)}
                  className={`rounded-md border border-border px-3 py-1 text-[13px] ${period === p ? "bg-surface-2 font-medium text-ink" : "text-ink-2"}`}>
            {p === "test" ? "Test year (frozen holdout)" : "Validation year"}
          </button>
        ))}
      </div>

      <Panel title="Leaderboard" subtitle={res ? `${res.from} → ${res.to} · ${res.n_hours.toLocaleString("en-GB")} scored hours · run ${res.run_id}` : "…"}
             footer="MAE/RMSE/bias in MW on hourly load. Peak MAE = error at each day's actual peak hour. Coverage = share of hours inside the 50%/90% interval (nominal 0.50/0.90). The TSO publishes a point forecast only, so it has no interval metrics. 'Oracle' uses hindsight weather and is an upper bound, not a usable forecast.">
        {!res ? <Skeleton height={220} /> : (
          <div className="overflow-x-auto">
            <table className="num w-full min-w-[760px] text-[13px]">
              <thead className="text-left text-[12px] text-ink-2">
                <tr className="border-b border-border">
                  <th className="py-1.5 pr-3">Model</th><th className="pr-3">MAE</th><th className="pr-3">RMSE</th><th className="pr-3">Bias</th>
                  <th className="pr-3">MAPE</th><th className="pr-3">Peak MAE</th><th className="pr-3">Skill vs TSO</th><th className="pr-3">Cov. 50%</th><th className="pr-3">Cov. 90%</th><th>Width 90%</th>
                </tr>
              </thead>
              <tbody>
                {res.leaderboard.map((r) => (
                  <tr key={r.model} className={`border-b border-border ${r.model === "gbm_weather" ? "font-semibold" : ""} ${r.label === "hindsight_oracle" ? "text-muted" : ""}`}>
                    <td className="py-1.5 pr-3">{MODEL_LABEL[r.model] ?? r.model}{r.label === "hindsight_oracle" && " †"}</td>
                    <td className="pr-3">{fmtMW(r.mae_mw)}</td><td className="pr-3">{fmtMW(r.rmse_mw)}</td>
                    <td className="pr-3">{r.bias_mw > 0 ? "+" : ""}{fmtMW(r.bias_mw)}</td><td className="pr-3">{r.mape_pct.toFixed(2)}%</td>
                    <td className="pr-3">{fmtMW(r.peak_mae_mw)}</td>
                    <td className="pr-3" style={{ color: r.skill_vs_tso > 0.0005 ? "var(--good-text)" : r.skill_vs_tso < -0.0005 ? "var(--critical)" : undefined }}>
                      {r.model === "tso_official" ? "—" : `${r.skill_vs_tso > 0 ? "▲ +" : r.skill_vs_tso < 0 ? "▼ " : ""}${fmtPct(r.skill_vs_tso)}`}
                    </td>
                    <td className="pr-3">{r.coverage_50 == null ? "—" : r.coverage_50.toFixed(3)}</td>
                    <td className="pr-3">{r.coverage_90 == null ? "—" : r.coverage_90.toFixed(3)}</td>
                    <td>{fmtMW(r.width_90_mw)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Error by hour of day" subtitle="MAE in MW by local delivery hour.">
          {hourOption ? <EChart option={hourOption} height={300} ariaLabel="MAE by hour of day per model" /> : <Skeleton height={300} />}
        </Panel>
        <Panel title="Error by month" subtitle="GridMind vs TSO official forecast, MAE in MW.">
          {monthOption ? <EChart option={monthOption} height={300} ariaLabel="MAE by month for GridMind and TSO" /> : <Skeleton height={300} />}
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Is the difference real?" subtitle="Diebold–Mariano test on daily mean absolute errors (Newey–West variance). Negative statistic = first model has lower error; p < 0.05 is conventionally significant.">
          {!res ? <Skeleton height={160} /> : (
            <table className="num w-full text-[13px]">
              <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border"><th className="py-1.5">Model</th><th>vs</th><th>DM stat</th><th>p-value</th><th>days</th></tr></thead>
              <tbody>{res.dm.map((d, k) => (
                <tr key={k} className="border-b border-border"><td className="py-1.5">{MODEL_LABEL[d.model]}</td><td>{MODEL_LABEL[d.vs] ?? d.vs}</td>
                  <td>{d.dm_stat == null ? "—" : d.dm_stat.toFixed(2)}</td><td>{d.p_value == null ? "—" : d.p_value < 0.0001 ? "<0.0001" : d.p_value.toFixed(4)}</td><td>{d.n_days}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
        <Panel title="Error by forecast temperature" subtitle="MAE (MW) by the delivery day's forecast mean temperature (population-weighted).">
          {!res ? <Skeleton height={160} /> : (
            <table className="num w-full text-[13px]">
              <thead className="text-left text-[12px] text-ink-2"><tr className="border-b border-border"><th className="py-1.5">Temperature</th>{["gbm_weather", "tso_official", "naive_d7"].map((m) => <th key={m}>{MODEL_LABEL[m]}</th>)}<th>hours</th></tr></thead>
              <tbody>{["<0°C", "0–10°C", "10–20°C", "≥20°C"].map((b) => {
                const cell = (m: string) => res.by_temp.find((r) => r.model === m && r.temp_bin === b);
                return <tr key={b} className="border-b border-border"><td className="py-1.5">{b}</td>{["gbm_weather", "tso_official", "naive_d7"].map((m) => <td key={m}>{fmtMW(cell(m)?.mae)}</td>)}<td>{cell("gbm_weather")?.hours ?? "—"}</td></tr>;
              })}</tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}
