"use client";

import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, LineChart, MapChart } from "echarts/charts";
import {
  DataZoomComponent,
  GeoComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([
  LineChart, BarChart, HeatmapChart, MapChart, GridComponent, TooltipComponent, LegendComponent,
  VisualMapComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, GeoComponent, CanvasRenderer,
]);

export { echarts };

export type Tokens = Record<
  "surface" | "ink" | "ink2" | "muted" | "grid" | "axis" | "s1" | "s2" | "s3" | "s4" | "s5" | "s6" | "s7" | "s8" |
  "tso" | "actual" | "band" | "bandInner" | "nodata" | "neutralMid" | "critical",
  string
>;

const VARS: Record<keyof Tokens, string> = {
  surface: "--surface", ink: "--ink", ink2: "--ink-2", muted: "--muted", grid: "--grid", axis: "--axis",
  s1: "--s1", s2: "--s2", s3: "--s3", s4: "--s4", s5: "--s5", s6: "--s6", s7: "--s7", s8: "--s8",
  tso: "--tso", actual: "--actual", band: "--band", bandInner: "--band-inner", nodata: "--nodata", neutralMid: "--neutral-mid",
  critical: "--critical",
};

function readTokens(): Tokens {
  const cs = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    Object.entries(VARS).map(([k, v]) => [k, cs.getPropertyValue(v).trim()]),
  ) as Tokens;
}

/** Re-reads tokens whenever the OS scheme or the data-theme attribute changes. */
export function useTokens(): Tokens | null {
  const [t, setT] = useState<Tokens | null>(null);
  useEffect(() => {
    const update = () => setT(readTokens());
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", update);
      mo.disconnect();
    };
  }, []);
  return t;
}

export function baseAxis(t: Tokens) {
  return {
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: t.grid, width: 1 } },
  };
}

export function baseTooltip(t: Tokens) {
  return {
    backgroundColor: t.surface,
    borderColor: t.axis,
    textStyle: { color: t.ink, fontSize: 12 },
    extraCssText: "box-shadow: 0 4px 16px rgba(0,0,0,.12); border-radius: 8px;",
  };
}

export function EChart({
  option,
  height = 320,
  ariaLabel,
  onEvents,
}: {
  option: EChartsCoreOption | null;
  height?: number;
  ariaLabel: string;
  onEvents?: Record<string, (p: unknown) => void>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !option) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    chart.current.setOption({ animation: !reduce, animationDuration: 300, ...option }, { notMerge: true });
  }, [option]);

  useEffect(() => {
    const c = chart.current;
    if (!c || !onEvents) return;
    Object.entries(onEvents).forEach(([ev, fn]) => c.on(ev, fn));
    return () => Object.keys(onEvents).forEach((ev) => c.off(ev));
  }, [onEvents]);

  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ width: "100%", height }} />;
}
