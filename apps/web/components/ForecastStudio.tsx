"use client";

import { useMemo, useState } from "react";
import { DataCredits } from "@/components/Credits";
import { EChart, baseAxis, baseTooltip, useTokens } from "@/components/EChart";
import { ErrorState, Panel, Skeleton, Stat } from "@/components/ui";
import { type Replay, fmtGW, fmtMW, useData } from "@/lib/data";

const TZ = "Europe/Berlin";
const timeFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const hourFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });

type Row = { t: number; y: number | null; tso: number | null; q05: number | null; q25: number | null; q50: number | null; q75: number | null; q95: number | null; issue: number; day: string };
// Scores are exported by the pipeline (day_scores); the browser only renders them.

function rowsOf(r: Replay): Row[] {
  const h = r.hourly;
  return h.valid_at_utc.map((v, i) => ({
    t: Date.parse(v), y: h.y[i], tso: h.tso_forecast[i], q05: h.q05[i], q25: h.q25[i], q50: h.q50[i], q75: h.q75[i],
    q95: h.q95[i], issue: Date.parse(h.issue_time_utc[i]), day: h.delivery_day[i],
  }));
}

export default function ForecastStudio() {
  const t = useTokens();
  const replay = useData<Replay>("forecast_replay.json");
  const [dayIdx, setDayIdx] = useState<number | null>(null);
  const [reveal, setReveal] = useState(true);

  const rows = useMemo(() => (replay.data ? rowsOf(replay.data) : []), [replay.data]);
  const days = replay.data?.days ?? [];
  const di = dayIdx ?? Math.max(0, days.length - 1);
  const day = days[di];

  const view = useMemo(() => {
    if (!day) return null;
    const target = rows.filter((r) => r.day === day);
    if (!target.length) return null;
    const issue = target[0].issue;
    const knownEnd = issue - 2 * 3600_000; // contract: actuals published with <= 2 h lag
    const context = rows.filter((r) => r.t >= issue - 34 * 3600_000 && r.t < target[0].t);
    const known = context.map((r) => [r.t, r.t + 3600_000 <= knownEnd ? r.y : null]);
    const sc = replay.data?.day_scores[day];
    return { target, issue, known, context, maeGM: sc?.mae_gridmind ?? null, maeTSO: sc?.mae_tso ?? null,
             cover90: sc?.coverage_90 ?? null, n: sc?.n ?? 0 };
  }, [rows, day, replay.data]);

  const option = useMemo(() => {
    if (!t || !view) return null;
    const tg = view.target;
    const lo = tg.map((r) => [r.t, r.q05]);
    const band90 = tg.map((r) => [r.t, r.q95 != null && r.q05 != null ? r.q95 - r.q05 : null]);
    const lo50 = tg.map((r) => [r.t, r.q25]);
    const band50 = tg.map((r) => [r.t, r.q75 != null && r.q25 != null ? r.q75 - r.q25 : null]);
    const stepLine = { type: "line", step: "start", showSymbol: false, connectNulls: false };
    return {
      grid: { left: 56, right: 20, top: 64, bottom: 44 },
      legend: { top: 0, left: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 14, itemHeight: 8,
                data: ["Known at issue", "GridMind median", "90% interval", "50% interval", "TSO official forecast", "Actual (revealed later)"] },
      tooltip: {
        ...baseTooltip(t), trigger: "axis",
        formatter: (ps: { seriesName: string; value: [number, number | null]; axisValue: number }[]) => {
          const ts = ps[0]?.value[0];
          const r = tg.find((x) => x.t === ts);
          const head = `<b>${timeFmt.format(ts)}</b> (local)`;
          if (!r) return `${head}<br/>Actual: ${fmtGW(ps.find((p) => p.seriesName === "Known at issue")?.value[1] ?? null)}`;
          return `${head}<br/>GridMind median: <b>${fmtGW(r.q50)}</b><br/>90% interval: ${fmtGW(r.q05)} – ${fmtGW(r.q95)}<br/>TSO forecast: ${fmtGW(r.tso)}${reveal ? `<br/>Actual: <b>${fmtGW(r.y)}</b>` : ""}`;
        },
      },
      xAxis: { type: "time", ...baseAxis(t), splitLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => hourFmt.format(v) } },
      yAxis: { type: "value", scale: true, ...baseAxis(t), name: "GW", nameTextStyle: { color: t.muted },
               axisLabel: { color: t.muted, formatter: (v: number) => `${(v / 1000).toFixed(0)}` } },
      series: [
        { ...stepLine, name: "Known at issue", data: view.known, lineStyle: { color: t.actual, width: 1.6 }, itemStyle: { color: t.actual },
          markLine: { symbol: "none", silent: true, lineStyle: { color: t.ink2, type: "solid", width: 1 },
                      label: { formatter: "Issue time\nD-1 10:00", color: t.ink2, fontSize: 11, position: "insideEndTop" },
                      data: [{ xAxis: view.issue }] },
          markArea: { silent: true, itemStyle: { color: t.grid, opacity: 0.45 },
                      label: { show: true, position: "insideTop", color: t.muted, fontSize: 10, formatter: "not yet\npublished" },
                      data: [[{ xAxis: view.issue - 2 * 3600_000 }, { xAxis: tg[0].t }]] } },
        { ...stepLine, name: "lo90", data: lo, stack: "b90", lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
        { ...stepLine, name: "90% interval", data: band90, stack: "b90", lineStyle: { opacity: 0 }, areaStyle: { color: t.band }, itemStyle: { color: t.band } },
        { ...stepLine, name: "lo50", data: lo50, stack: "b50", lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
        { ...stepLine, name: "50% interval", data: band50, stack: "b50", lineStyle: { opacity: 0 }, areaStyle: { color: t.bandInner }, itemStyle: { color: t.bandInner } },
        { ...stepLine, name: "GridMind median", data: tg.map((r) => [r.t, r.q50]), lineStyle: { color: t.s1, width: 2 }, itemStyle: { color: t.s1 } },
        { ...stepLine, name: "TSO official forecast", data: tg.map((r) => [r.t, r.tso]), lineStyle: { color: t.tso, width: 1.5, type: "dashed" }, itemStyle: { color: t.tso } },
        ...(reveal ? [{ ...stepLine, name: "Actual (revealed later)", data: tg.map((r) => [r.t, r.y]), lineStyle: { color: t.actual, width: 1.6 }, itemStyle: { color: t.actual }, z: 5 }] : []),
      ],
    };
  }, [t, view, reveal]);

  if (replay.error) return <ErrorState message={replay.error} onRetry={replay.retry} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Forecast Studio</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          Replay any day of the frozen test year exactly as the forecast was made. Each forecast is issued at{" "}
          <b>10:00 the day before</b> (the TSOs&apos; own publication deadline), using only load data published by then and the
          GFS temperature forecast made 48 hours before each hour. The TSOs&apos; official forecast is shown for comparison.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
        <button className="rounded-md border border-border px-2.5 py-1 text-[13px]" onClick={() => setDayIdx(Math.max(0, di - 1))} disabled={di <= 0} aria-label="Previous day">←</button>
        <label className="flex flex-1 items-center gap-3 text-[13px] text-ink-2">
          <span className="num whitespace-nowrap font-medium text-ink">Delivery day {day ?? "…"}</span>
          <input type="range" min={0} max={Math.max(0, days.length - 1)} value={di} onChange={(e) => setDayIdx(Number(e.target.value))}
                 className="w-full accent-[var(--accent)]" aria-label="Select delivery day" />
        </label>
        <button className="rounded-md border border-border px-2.5 py-1 text-[13px]" onClick={() => setDayIdx(Math.min(days.length - 1, di + 1))} disabled={di >= days.length - 1} aria-label="Next day">→</button>
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} /> Reveal actuals
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="GridMind MAE (this day)" value={reveal ? fmtMW(view?.maeGM) : "hidden"} note={view ? `${view.n} scored hours` : undefined} />
        <Stat label="TSO forecast MAE (this day)" value={reveal ? fmtMW(view?.maeTSO) : "hidden"} />
        <Stat label="Hours inside 90% interval" value={reveal && view?.cover90 != null ? `${Math.round(view.cover90 * 100)}%` : "—"} note="nominal 90%; judge over many days, not one" />
        <Stat label="Issued at (local)" value={view ? hourFmt.format(view.issue) : "…"} note={view ? timeFmt.format(view.issue) : undefined} />
      </div>

      <Panel title="Day-ahead hourly load forecast" subtitle="GW. Left of the issue line: what was known when the forecast was made. Right: the forecast for the delivery day."
             footer={<>Model: {replay.data?.model ?? "…"} · {replay.data?.issue_rule ?? ""} · Bands are conformally calibrated quantiles. <DataCredits /></>}>
        {option ? <EChart option={option} height={400} ariaLabel={`Forecast fan chart for ${day}`} /> : <Skeleton height={400} />}
      </Panel>
    </div>
  );
}
