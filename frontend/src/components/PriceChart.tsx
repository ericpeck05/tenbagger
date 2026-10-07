import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  LineStyle,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Bar, Prices, Quote } from "../api";
import { withLiveBar } from "../chart";

export type ChartKind = "candles" | "line";

const C = {
  panel: "#0A0A0A",
  border: "#2A2A2A",
  grid: "#1F1F1F",
  muted: "#9A9A9A",
  strong: "#3A3A3A",
  accent: "#FFA31A",
  up: "#2BD67B",
  down: "#FF4D4D",
};

type Props = {
  prices: Prices | undefined;
  quote: Quote | null;
  kind: ChartKind;
  onHover: (bar: Bar | null) => void;
};

export function PriceChart({ prices, quote, kind, onHover }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const area = useRef<ISeriesApi<"Area"> | null>(null);
  const priceLine = useRef<{
    series: ISeriesApi<"Candlestick"> | ISeriesApi<"Area">;
    line: IPriceLine;
  } | null>(null);
  const [ready, setReady] = useState(false);

  const bars = useMemo(() => (prices ? withLiveBar(prices, quote) : []), [prices, quote]);
  const byTime = useMemo(() => new Map(bars.map((b) => [b.time, b])), [bars]);

  // Create the chart once.
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.panel },
        textColor: C.muted,
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 12,
        attributionLogo: false, // credited in the source line instead
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: C.grid, style: LineStyle.Dashed },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: C.muted, style: LineStyle.Dashed, labelBackgroundColor: C.strong },
        horzLine: { color: C.muted, style: LineStyle.Dashed, labelBackgroundColor: C.strong },
      },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.08, bottom: 0.06 } },
      timeScale: { borderColor: C.border, rightOffset: 3, fixLeftEdge: true, lockVisibleTimeRangeOnResize: true },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    });
    candles.current = c.addSeries(CandlestickSeries, {
      upColor: C.up,
      downColor: C.down,
      borderUpColor: C.up,
      borderDownColor: C.down,
      wickUpColor: C.up,
      wickDownColor: C.down,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    area.current = c.addSeries(AreaSeries, {
      lineColor: C.accent,
      lineWidth: 2,
      topColor: "rgba(255, 163, 26, 0.16)",
      bottomColor: "rgba(255, 163, 26, 0)",
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerBorderColor: C.panel,
      crosshairMarkerBackgroundColor: C.accent,
    });
    chart.current = c;
    setReady(true);
    return () => {
      c.remove();
      chart.current = candles.current = area.current = null;
      priceLine.current = null;
    };
  }, []);

  // Data and chart type.
  useEffect(() => {
    if (!ready || !candles.current || !area.current || !chart.current) return;
    const data = bars.map((b) => ({ ...b, time: b.time as Time }));
    candles.current.setData(kind === "candles" ? data : []);
    area.current.setData(kind === "line" ? data.map((b) => ({ time: b.time, value: b.close })) : []);
    // The last price: a dashed amber line with an inverse amber label on the axis.
    if (priceLine.current) {
      priceLine.current.series.removePriceLine(priceLine.current.line);
      priceLine.current = null;
    }
    const last = bars[bars.length - 1];
    if (last) {
      const series = kind === "candles" ? candles.current : area.current;
      const line = series.createPriceLine({
        price: last.close,
        color: C.accent,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        axisLabelColor: C.accent,
        axisLabelTextColor: "#000000",
      });
      priceLine.current = { series, line };
    }
    chart.current.timeScale().fitContent();
  }, [ready, bars, kind]);

  // OHLC readout follows the crosshair, falling back to the latest bar.
  useEffect(() => {
    const c = chart.current;
    if (!ready || !c) return;
    const handler = (p: MouseEventParams) => {
      const key = timeKey(p.time);
      onHover(key ? (byTime.get(key) ?? null) : null);
    };
    c.subscribeCrosshairMove(handler);
    return () => c.unsubscribeCrosshairMove(handler);
  }, [ready, byTime, onHover]);

  return (
    <div className="chart-box">
      <div ref={box} className="chart-canvas" />
      {prices && prices.bars.length === 0 && (
        <div className="chart-empty">No price history for this ticker yet</div>
      )}
      {!prices && <div className="chart-empty">Loading prices</div>}
    </div>
  );
}

/** The chart reports a hovered day as a string, a {year, month, day} object, or a UTC
 *  timestamp depending on how data was given; normalise to YYYY-MM-DD. */
function timeKey(t: Time | undefined): string | null {
  if (t === undefined) return null;
  if (typeof t === "string") return t;
  if (typeof t === "number") return new Date(t * 1000).toISOString().slice(0, 10);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${t.year}-${pad(t.month)}-${pad(t.day)}`;
}
