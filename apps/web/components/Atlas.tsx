"use client";

import { useEffect, useMemo, useState } from "react";
import { DataCredits } from "@/components/Credits";
import { EChart, baseAxis, baseTooltip, echarts, useTokens, type Tokens } from "@/components/EChart";
import { ErrorState, Panel, Skeleton, SourceNote, Stat } from "@/components/ui";
import { type Atlas, ZONE_LABEL, fmtGW, fmtMW, fmtPct, useData } from "@/lib/data";

const AREAS = ["DE_50HZ", "DE_AMPRION", "DE_TENNET", "DE_TRANSNETBW"] as const;
const GEN_ORDER: { key: string; label: string; token: keyof Tokens }[] = [
  { key: "wind", label: "Wind", token: "s1" },
  { key: "solar", label: "Solar", token: "s4" },
  { key: "other_renewables", label: "Other renewables", token: "s3" },
  { key: "gas", label: "Gas", token: "s2" },
  { key: "coal", label: "Coal", token: "s7" },
  { key: "other_and_storage", label: "Other & storage", token: "s5" },
];
type MapMetric = "level" | "anomaly" | "skill";
type CA = { chosen_method: string; series: Record<string, { mae_gridmind: number; mae_tso: number; skill_vs_tso: number }> };

function useGeo() {
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch("/data/de_states.geojson")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((gj) => {
        echarts.registerMap("de_states", gj);
        setOk(true);
      })
      .catch((e: Error) => setErr(e.message));
  }, []);
  return { ok, err };
}

/** Value of an area on a date and its exported anomaly vs the same period last year. */
function areaStats(atlas: Atlas, zone: string, date: string) {
  const r = atlas.regions[zone];
  const i = r ? r.date.indexOf(date) : -1;
  return { v: i >= 0 ? r.load_mw[i] : null, anomaly: i >= 0 ? r.anomaly[i] : null };
}

export default function AtlasView() {
  const t = useTokens();
  const atlas = useData<Atlas>("atlas.json");
  const ca = useData<CA>("control_areas.json");
  const geo = useGeo();
  const dates = atlas.data?.regions.DE_LU?.date ?? [];
  const [idx, setIdx] = useState<number | null>(null);
  const [metric, setMetric] = useState<MapMetric>("anomaly");
  const [showTable, setShowTable] = useState(false);
  const lastComplete = useMemo(() => {
    const v = atlas.data?.regions.DE_LU?.load_mw ?? [];
    for (let k = v.length - 1; k >= 0; k--) if (v[k] != null) return k;
    return Math.max(0, v.length - 1);
  }, [atlas.data]);
  const i = idx ?? lastComplete;
  const date = dates[i];

  const areaValues = useMemo(() => {
    if (!atlas.data || !date) return [];
    return AREAS.map((z) => ({ zone: z, ...areaStats(atlas.data!, z, date) }));
  }, [atlas.data, date]);

  const mapOption = useMemo(() => {
    if (!t || !geo.ok || !areaValues.length) return null;
    const byZone = Object.fromEntries(areaValues.map((a) => [a.zone, a]));
    const gj = echarts.getMap("de_states") as unknown as {
      geoJSON: { features: { properties: { name: string; control_area: string; shared_control_area: boolean } }[] };
    };
    const data = gj.geoJSON.features.map((f) => {
      const a = byZone[f.properties.control_area];
      const sk = ca.data?.series[f.properties.control_area];
      const value = metric === "skill" ? (sk ? sk.skill_vs_tso * 100 : null)
        : metric === "level" ? a?.v ?? null : a?.anomaly != null ? a.anomaly * 100 : null;
      return {
        name: f.properties.name, value, area: f.properties.control_area, shared: f.properties.shared_control_area,
        ...(value == null ? { itemStyle: { areaColor: t.surface, decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: Math.PI / 4, color: t.axis } } } : {}),
      };
    });
    const levels = areaValues.map((a) => a.v).filter((x): x is number => x != null);
    return {
      tooltip: {
        ...baseTooltip(t),
        formatter: (p: { name: string; data?: { value: number | null; area: string; shared: boolean } }) => {
          const a = p.data && byZone[p.data.area];
          if (metric === "skill") {
            const sk = p.data && ca.data?.series[p.data.area];
            if (!p.data || !sk) return `${p.name}<br/>No forecast data`;
            return `<b>${p.name}</b> → ${ZONE_LABEL[p.data.area]}<br/>Test-year MAE, GridMind (reconciled): <b>${fmtMW(sk.mae_gridmind)}</b><br/>
              TSO day-ahead forecast: <b>${fmtMW(sk.mae_tso)}</b><br/>Skill vs TSO: <b>${fmtPct(sk.skill_vs_tso, 1, true)}</b>`;
          }
          if (!p.data || !a) return `${p.name}<br/>No data`;
          return `<b>${p.name}</b> → ${ZONE_LABEL[p.data.area]}${p.data.shared ? " (state shared between TSOs)" : ""}<br/>
            Control-area daily mean load: <b>${fmtGW(a.v)}</b><br/>vs same period last year (±7 days): <b>${a.anomaly == null ? "—" : fmtPct(a.anomaly, 1, true)}</b>`;
        },
      },
      visualMap:
        metric === "skill"
          ? {
              min: -40, max: 40, calculable: false, orient: "horizontal", left: 0, bottom: 0, itemWidth: 10, itemHeight: 160,
              textStyle: { color: t.muted, fontSize: 11 }, text: ["GridMind better", "TSO better"], showLabel: true,
              inRange: { color: ["#c22f2f", "#f1a3a2", t.neutralMid, "#86b6ef", "#1c5cab"] },
            }
          : metric === "level"
          ? {
              min: Math.min(...levels) * 0.95, max: Math.max(...levels) * 1.02, calculable: false, orient: "horizontal",
              left: 0, bottom: 0, itemWidth: 10, itemHeight: 160, textStyle: { color: t.muted, fontSize: 11 },
              inRange: { color: ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"] },
              formatter: (v: number) => `${(v / 1000).toFixed(0)} GW`, text: ["higher", "lower"], showLabel: true,
            }
          : {
              min: -10, max: 10, calculable: false, orient: "horizontal", left: 0, bottom: 0, itemWidth: 10, itemHeight: 160,
              textStyle: { color: t.muted, fontSize: 11 }, formatter: (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`,
              text: ["≥ +10%", "≤ −10%"], showLabel: true,
              inRange: { color: ["#1c5cab", "#86b6ef", t.neutralMid, "#f1a3a2", "#c22f2f"] },
            },
      series: [{
        type: "map", map: "de_states", roam: false, data, nameProperty: "name", aspectScale: 0.65,
        itemStyle: { areaColor: t.nodata, borderColor: t.surface, borderWidth: 1.2 },
        emphasis: { label: { show: false }, itemStyle: { borderColor: t.ink, borderWidth: 1.5 } },
        select: { disabled: true }, label: { show: false },
      }],
    };
  }, [t, geo.ok, areaValues, metric, ca.data]);

  const lineOption = useMemo(() => {
    if (!t || !atlas.data) return null;
    const r = atlas.data.regions.DE_LU;
    return {
      grid: { left: 52, right: 16, top: 16, bottom: 56 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number | null) => fmtGW(v) },
      xAxis: { type: "category", data: r.date, ...baseAxis(t), splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis(t), axisLabel: { color: t.muted, formatter: (v: number) => `${v / 1000}` },
               name: "GW", nameTextStyle: { color: t.muted }, scale: true },
      dataZoom: [{ type: "slider", height: 18, bottom: 8, borderColor: t.grid, textStyle: { color: t.muted } }, { type: "inside" }],
      series: [{
        type: "line", name: "Daily mean load", data: r.load_mw, showSymbol: false, connectNulls: false,
        lineStyle: { width: 1.6, color: t.s1 }, itemStyle: { color: t.s1 },
        markLine: { symbol: "none", silent: true, label: { show: false }, lineStyle: { color: t.ink2, type: "dashed" },
                    data: date ? [{ xAxis: date }] : [] },
      }],
    };
  }, [t, atlas.data, date]);

  const carpetOption = useMemo(() => {
    if (!t || !atlas.data) return null;
    const c = atlas.data.carpet;
    const data: [number, number, number | null][] = [];
    let lo = Infinity, hi = -Infinity;
    c.load_mw.forEach((row, x) => row.forEach((v, y) => {
      data.push([x, y, v]);
      if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }));
    return {
      grid: { left: 44, right: 16, top: 8, bottom: 52 },
      tooltip: { ...baseTooltip(t), formatter: (p: { value: [number, number, number | null] }) =>
        `${c.dates[p.value[0]]} · ${String(p.value[1]).padStart(2, "0")}:00 local<br/><b>${fmtGW(p.value[2])}</b>` },
      xAxis: { type: "category", data: c.dates, ...baseAxis(t), splitLine: { show: false },
               axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true } },
      yAxis: { type: "category", data: c.hours.map((h) => `${String(h).padStart(2, "0")}h`), ...baseAxis(t),
               splitLine: { show: false }, axisLabel: { color: t.muted, fontSize: 10, interval: 5 } },
      visualMap: { min: lo, max: hi, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemWidth: 10,
                   itemHeight: 200, textStyle: { color: t.muted, fontSize: 11 },
                   formatter: (v: number) => `${(v / 1000).toFixed(0)} GW`,
                   inRange: { color: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"] },
                   outOfRange: { color: t.nodata } },
      series: [{ type: "heatmap", data, progressive: 0, itemStyle: { borderWidth: 0 } }],
    };
  }, [t, atlas.data]);

  const genOption = useMemo(() => {
    if (!t || !atlas.data) return null;
    const g = atlas.data.generation_mix;
    return {
      grid: { left: 52, right: 16, top: 16, bottom: 40 },
      legend: { bottom: 0, textStyle: { color: t.ink2, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
      tooltip: { ...baseTooltip(t), trigger: "axis", valueFormatter: (v: number | null) => fmtGW(v) },
      xAxis: { type: "category", data: g.dates, ...baseAxis(t), splitLine: { show: false }, boundaryGap: false },
      yAxis: { type: "value", ...baseAxis(t), axisLabel: { color: t.muted, formatter: (v: number) => `${v / 1000}` },
               name: "GW", nameTextStyle: { color: t.muted } },
      series: GEN_ORDER.map((s) => ({
        type: "line", name: s.label, stack: "gen", data: g.series[s.key], showSymbol: false, connectNulls: false,
        lineStyle: { width: 0 }, areaStyle: { color: t[s.token], opacity: 0.92 }, itemStyle: { color: t[s.token] },
        emphasis: { focus: "series" },
      })),
    };
  }, [t, atlas.data]);

  if (atlas.error) return <ErrorState message={atlas.error} onRetry={atlas.retry} />;
  const de = atlas.data && date ? areaStats(atlas.data, "DE_LU", date) : null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Energy Atlas</h1>
        <p className="mt-1 max-w-3xl text-[14px] text-ink-2">
          Observed electricity load in Germany–Luxembourg and the four German transmission-system-operator (TSO)
          control areas. Values are daily means of hourly load in GW, published by the TSOs via SMARD. A grey area
          means no data for that day, never zero.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label={`DE-LU daily mean load · ${date ?? "…"}`} value={de ? fmtGW(de.v) : "…"}
              note={de?.anomaly != null ? `${fmtPct(de.anomaly, 1, true)} vs same period last year` : undefined} />
        {areaValues.map((a) => (
          <Stat key={a.zone} label={ZONE_LABEL[a.zone]} value={fmtGW(a.v)}
                note={a.anomaly != null ? `${fmtPct(a.anomaly, 1, true)} vs same period last year` : "—"} />
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Panel
          title="Control areas"
          subtitle={
            <span className="flex flex-wrap items-center gap-2">
              <span>Colour:</span>
              {(["anomaly", "level", "skill"] as MapMetric[]).map((m) => (
                <button key={m} onClick={() => setMetric(m)} aria-pressed={metric === m}
                        className={`rounded-md border border-border px-2 py-0.5 text-[12px] ${metric === m ? "bg-surface-2 text-ink" : "text-ink-2"}`}>
                  {m === "anomaly" ? "vs same period last year (%)" : m === "level" ? "daily mean load (GW)" : "forecast skill vs TSO (test year)"}
                </button>
              ))}
            </span>
          }
          footer="Hatched = no data for that day. States are coloured by the TSO that covers most of them; Hesse, Lower Saxony and Bavaria are shared between TSOs, so the borders are approximate. Boundaries: Natural Earth."
        >
          {geo.err ? <ErrorState message={geo.err} /> : mapOption ? <EChart option={mapOption} height={420} ariaLabel={metric === "skill" ? "Map of German TSO control areas coloured by skill vs the TSO forecast over the test year" : `Map of German TSO control areas coloured by ${metric} on ${date}`} /> : <Skeleton height={420} />}
          {dates.length > 0 && (
            <label className="mt-2 block text-[12px] text-ink-2">
              <span className="num">Day: {date}</span>
              <input type="range" min={0} max={dates.length - 1} value={i} onChange={(e) => setIdx(Number(e.target.value))}
                     className="mt-1 w-full accent-[var(--accent)]" aria-label="Select day" />
            </label>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel title="Germany–Luxembourg: daily mean load" subtitle="GW, last 2 years. The dashed line marks the selected day. Drag the slider to zoom."
                 footer={<>Actual total load; a day with any missing hour is left blank. <DataCredits weather={false} /></>}>
            {lineOption ? <EChart option={lineOption} height={260} ariaLabel="Line chart of daily mean load in Germany-Luxembourg" /> : <Skeleton height={260} />}
          </Panel>
          <Panel title="Load carpet: day × hour" subtitle="Each cell is one local hour of the last 365 days. Daily rhythm, weekends, holidays and seasons in one view."
                 footer="Hours in Europe/Berlin time. On the 25-hour DST day, the repeated 02:00 hour shows its first occurrence.">
            {carpetOption ? <EChart option={carpetOption} height={300} ariaLabel="Heatmap of hourly load by day and hour" /> : <Skeleton height={300} />}
          </Panel>
        </div>
      </div>

      <Panel
        title="Generation mix, DE-LU"
        subtitle={<>Daily mean generation by source group, GW, last 365 days. <button className="underline" onClick={() => setShowTable((s) => !s)}>{showTable ? "Hide" : "Show"} table</button></>}
        footer={`Groups: wind = onshore + offshore; other renewables = biomass + hydro + other; coal = lignite + hard coal; other & storage = other conventional + pumped-storage generation. Excluded (no data in window): ${atlas.data?.generation_mix.excluded_no_data_in_window?.join(", ") || "none"}. Generation is not the same as load: imports, exports and storage close the gap.`}
      >
        {genOption ? <EChart option={genOption} height={340} ariaLabel="Stacked area chart of daily generation by source" /> : <Skeleton height={340} />}
        {showTable && atlas.data && (
          <div className="mt-3 max-h-72 overflow-auto rounded-md border border-border">
            <table className="num w-full text-[12px]">
              <thead className="sticky top-0 bg-surface-2 text-left text-ink-2">
                <tr><th className="px-2 py-1">Date</th>{GEN_ORDER.map((s) => <th key={s.key} className="px-2 py-1">{s.label} (GW)</th>)}</tr>
              </thead>
              <tbody>
                {atlas.data.generation_mix.dates.slice().reverse().map((d, k) => {
                  const j = atlas.data!.generation_mix.dates.length - 1 - k;
                  return (
                    <tr key={d} className="border-t border-border">
                      <td className="px-2 py-1">{d}</td>
                      {GEN_ORDER.map((s) => <td key={s.key} className="px-2 py-1">{fmtGW(atlas.data!.generation_mix.series[s.key]?.[j]).replace(" GW", "")}</td>)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <SourceNote>Data generated {atlas.data?.generated_at ?? "…"} · data through {atlas.data?.data_end_utc ?? "…"}</SourceNote>
    </div>
  );
}
