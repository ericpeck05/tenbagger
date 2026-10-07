import {
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { Performance } from "../api";

const C = {
  panel: "#0A0A0A",
  border: "#2A2A2A",
  grid: "#1F1F1F",
  muted: "#9A9A9A",
  strong: "#3A3A3A",
  accent: "#FFA31A",
  zero: "#5A5A5A",
};

const pctFormat = (v: number) => `${v > 0 ? "+" : v < 0 ? "-" : ""}${Math.abs(v).toFixed(1)}%`;

/** Portfolio return (amber line) against the benchmark (grey dashed line), in percent. */
export function PerformanceChart({ data }: { data: Performance | undefined }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const port = useRef<ISeriesApi<"Line"> | null>(null);
  const bench = useRef<ISeriesApi<"Line"> | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.panel },
        textColor: C.muted,
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 12,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: C.grid, style: LineStyle.Dashed } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: C.muted, style: LineStyle.Dashed, labelBackgroundColor: C.strong },
        horzLine: { color: C.muted, style: LineStyle.Dashed, labelBackgroundColor: C.strong },
      },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.1, bottom: 0.08 } },
      timeScale: { borderColor: C.border, fixLeftEdge: true, fixRightEdge: true },
      localization: { priceFormatter: pctFormat },
      handleScroll: false,
      handleScale: false,
    });
    bench.current = c.addSeries(LineSeries, {
      color: C.muted,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    });
    port.current = c.addSeries(LineSeries, {
      color: C.accent,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerBackgroundColor: C.accent,
      crosshairMarkerBorderColor: C.panel,
    });
    // The 0% line.
    port.current.createPriceLine({
      price: 0,
      color: C.zero,
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: false,
    });
    chart.current = c;
    setReady(true);
    return () => {
      c.remove();
      chart.current = port.current = bench.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready || !data || !port.current || !bench.current || !chart.current) return;
    port.current.setData(data.points.map((p) => ({ time: p.time as Time, value: p.portfolio * 100 })));
    bench.current.setData(
      data.points
        .filter((p) => p.benchmark != null)
        .map((p) => ({ time: p.time as Time, value: (p.benchmark ?? 0) * 100 })),
    );
    chart.current.timeScale().fitContent();
  }, [ready, data]);

  return (
    <div className="chart-box perf-box">
      <div ref={box} className="chart-canvas" />
      {data && data.points.length === 0 && (
        <div className="chart-empty">Add a trade to start the performance history</div>
      )}
      {!data && <div className="chart-empty">Loading</div>}
    </div>
  );
}
