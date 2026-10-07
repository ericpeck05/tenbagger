import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { api, type Bar, type ChartRange, keys, type Lynch, type LynchTest, type Stock } from "../api";
import { Panel } from "../components/Panel";
import { lastBar } from "../chart";
import { type ChartKind, PriceChart } from "../components/PriceChart";
import { RatioCards } from "../components/RatioCards";
import { WatchlistColumn } from "../components/Watchlist";
import { ago, big, DASH, longDate, num, signed, signedPctPoints, tone } from "../format";
import { useDemo } from "../hooks/useDemo";
import { useHotkeys } from "../hooks/useHotkeys";
import { jumpTo, PANELS } from "../panels";

const RANGES: ChartRange[] = ["1M", "6M", "YTD", "1Y", "5Y", "MAX"];
const RANGE_WORDS: Record<ChartRange, string> = {
  "1M": "1 month",
  "6M": "6 months",
  YTD: "year to date",
  "1Y": "1 year",
  "5Y": "5 years",
  MAX: "since 2016",
};

function readPref<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage unavailable
  }
}

export function StockPage({ ticker }: { ticker: string }) {
  const qc = useQueryClient();
  const [range, setRange] = useState<ChartRange>(() => readPref("chart.range", "1Y", RANGES));
  const [kind, setKind] = useState<ChartKind>(() =>
    readPref("chart.kind", "candles", ["candles", "line"] as const),
  );

  const stock = useQuery({
    queryKey: keys.stock(ticker),
    queryFn: () => api.stock(ticker),
    placeholderData: keepPreviousData,
    // Poll quickly while the backend is fetching a fresh quote, then once a minute.
    refetchInterval: (query) => (query.state.data?.quote_refreshing ? 1_500 : 60_000),
  });
  const prices = useQuery({
    queryKey: keys.prices(ticker, range),
    queryFn: () => api.prices(ticker, range),
    placeholderData: (prev) => (prev?.ticker === ticker ? prev : undefined),
    staleTime: 5 * 60_000,
  });

  // A cold stock's first open fetches its price history; refresh the stock once it lands so
  // price-based 5-year ranges can be drawn.
  const needsPrices = stock.data?.ticker === ticker && stock.data.ranges_5y.missing_prices;
  const pricesLoaded = prices.data?.ticker === ticker && prices.data.bars.length > 0;
  useEffect(() => {
    if (needsPrices && pricesLoaded) qc.invalidateQueries({ queryKey: keys.stock(ticker) });
  }, [needsPrices, pricesLoaded, qc, ticker]);

  // keepPreviousData: the previous stock stays on screen until the next one is ready.
  const s = stock.data;
  const showing = s;

  const watch = useMutation({
    mutationFn: (on: boolean) => (on ? api.watch(ticker) : api.unwatch(ticker)),
    onSuccess: (wl) => {
      qc.setQueryData(keys.watchlist, wl);
      qc.invalidateQueries({ queryKey: keys.stock(ticker) });
    },
  });

  useHotkeys(
    useCallback(
      (e: KeyboardEvent) => {
        const panel = PANELS.find((p) => String(p.n) === e.key);
        if (panel) {
          jumpTo(panel.id);
          return true;
        }
        if (e.key === "w" || e.key === "W") {
          if (s && s.ticker === ticker) watch.mutate(!s.watching);
          return true;
        }
        return false;
      },
      [s, ticker, watch],
    ),
  );

  useEffect(() => {
    try {
      localStorage.setItem("lastTicker", ticker);
    } catch {
      // storage unavailable
    }
    document.title = `${ticker} · Tenbagger`;
  }, [ticker]);

  if (stock.isError && !s) {
    return (
      <Layout ticker={ticker}>
        <div className="notice">
          <strong>{ticker}</strong> {String(stock.error.message)}. Press <span className="key">/</span>{" "}
          to search.
        </div>
      </Layout>
    );
  }

  return (
    <Layout ticker={ticker}>
      {showing ? (
        <StockBody
          s={showing}
          loadingNext={showing.ticker !== ticker}
          prices={prices.data?.ticker === showing.ticker ? prices.data : undefined}
          range={range}
          setRange={(r) => {
            setRange(r);
            savePref("chart.range", r);
          }}
          kind={kind}
          setKind={(k) => {
            setKind(k);
            savePref("chart.kind", k);
          }}
          onWatch={() => watch.mutate(!showing.watching)}
        />
      ) : (
        <SkeletonBody />
      )}
    </Layout>
  );
}

function Layout({ ticker, children }: { ticker: string; children: React.ReactNode }) {
  return (
    <div className="page">
      <WatchlistColumn current={ticker} />
      <main className="main">{children}</main>
    </div>
  );
}

type BodyProps = {
  s: Stock;
  loadingNext: boolean;
  prices: import("../api").Prices | undefined;
  range: ChartRange;
  setRange: (r: ChartRange) => void;
  kind: ChartKind;
  setKind: (k: ChartKind) => void;
  onWatch: () => void;
};

function StockBody({ s, loadingNext, prices, range, setRange, kind, setKind, onWatch }: BodyProps) {
  const demo = useDemo();
  const r = s.ratios ?? {};
  const q = s.quote;
  const [hover, setHover] = useState<Bar | null>(null);
  const shown = hover ?? lastBar(prices, q);
  const weekly = prices?.interval === "1w";
  const r52 = s.range_52w ?? prices?.range_52w ?? null;

  return (
    <div className={loadingNext ? "body is-loading" : "body"}>
      {/* Header */}
      <section className="stock-head">
        <div className="stock-id">
          <div className="stock-title">
            <h1>{s.ticker}</h1>
            <span className="company">{s.name}</span>
            {s.exchange && <span className="chip">{s.exchange}</span>}
            {s.sector && <span className="chip">{s.sector}</span>}
            {!s.supported && (
              <span className="chip chip-pending" title="Version 1 covers us-gaap filers only">
                Foreign filer, no fundamentals
              </span>
            )}
            {s.supported && !s.ratios && (
              <span className="chip chip-pending" title="EDGAR has no XBRL financial data for this company">
                No reported financials
              </span>
            )}
            {s.lynch?.category && <span className="chip chip-on-static">{s.lynch.category}</span>}
            {demo && <span className="chip chip-pending">Sample data</span>}
            <button
              type="button"
              className={s.watching ? "chip chip-btn chip-on" : "chip chip-btn"}
              onClick={onWatch}
              aria-pressed={s.watching}
            >
              {s.watching ? "Watching" : "Watch"} <span className="key-inline">W</span>
            </button>
          </div>
          <div className="stock-price">
            <span className="price num">{q ? num(q.price) : DASH}</span>
            {q && (
              <span className={`day-change num ${tone(q.change)}`}>
                {signed(q.change)} {signedPctPoints(q.change_pct)}
              </span>
            )}
            <span className="price-note">
              {q ? (s.market_open ? `USD, ${ago(q.fetched_at)}` : `USD, at close`) : "No quote yet"}
            </span>
          </div>
        </div>
        <div className="stat-strip">
          <Stat label="Mkt cap" value={big(r.market_cap)} />
          <Stat label="P/E" value={num(r.pe, 1)} />
          <Stat label="PEG" value={num(r.peg, 2)} />
          <Stat
            label="Lynch"
            value={s.lynch?.score != null ? `${Math.round(s.lynch.score)} / 100` : DASH}
          />
          <div className="stat stat-range">
            <div className="stat-label">52-week range</div>
            <RangeBar low={r52?.low} high={r52?.high} value={q?.price} />
          </div>
        </div>
      </section>

      {/* 1 Price */}
      <Panel
        number={1}
        id="price"
        title="Price"
        note={
          <>
            <span className="panel-note">
              {weekly ? "Weekly" : "Daily"} {kind === "candles" ? "candles" : "closes"},{" "}
              {RANGE_WORDS[range]}
            </span>
            {prices?.change_pct != null && (
              <span className={`num ${tone(prices.change_pct)}`}>
                {signedPctPoints(prices.change_pct, 1)}
              </span>
            )}
          </>
        }
        right={
          <div className="chart-controls">
            <div role="group" aria-label="Chart type" className="seg">
              {(["candles", "line"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={kind === k}
                  className={kind === k ? "seg-btn seg-wide on" : "seg-btn seg-wide"}
                  onClick={() => setKind(k)}
                >
                  {k === "candles" ? "Candles" : "Line"}
                </button>
              ))}
            </div>
            <div role="group" aria-label="Chart range" className="seg">
              {RANGES.map((rg) => (
                <button
                  key={rg}
                  type="button"
                  aria-pressed={range === rg}
                  className={range === rg ? "seg-btn on" : "seg-btn"}
                  onClick={() => setRange(rg)}
                >
                  {rg}
                </button>
              ))}
            </div>
          </div>
        }
        bodyClass="price-body"
      >
        <div className="ohlc num">
          <span>
            <b>O</b> {num(shown?.open)}
          </span>
          <span>
            <b>H</b> {num(shown?.high)}
          </span>
          <span>
            <b>L</b> {num(shown?.low)}
          </span>
          <span>
            <b>C</b> {num(shown?.close)}
          </span>
          <span className="muted-caps">
            {hover ? longDate(hover.time) : weekly ? "Latest week" : "Latest day"}
          </span>
        </div>
        <PriceChart prices={prices} quote={q} kind={kind} onHover={setHover} />
        <div className="price-foot num">
          <span>
            <b>Prev close</b> {num(q?.prev_close)}
          </span>
          <span>
            <b>Open</b> {num(q?.open)}
          </span>
          <span>
            <b>Day range</b> {q?.low != null ? `${num(q.low)} to ${num(q.high)}` : DASH}
          </span>
          <span>
            <b>Shares out</b> {big(r.shares_outstanding, 2)}
          </span>
          <span className="legend">
            <span>
              <i className="swatch" style={{ background: "var(--up)" }} />
              Up {weekly ? "week" : "day"}
            </span>
            <span>
              <i className="swatch" style={{ background: "var(--down)" }} />
              Down {weekly ? "week" : "day"}
            </span>
          </span>
        </div>
      </Panel>

      {/* 2 Lynch */}
      <LynchPanel lynch={s.lynch} />

      {/* 3-6 Ratio cards */}
      <RatioCards stock={s} />

      <div className="two-up">
        {/* 7 Trend */}
        <Panel number={7} id="trend" title="10-year trend" className="trend-panel">
          <div className="trend">
            <TrendBars
              label="Revenue"
              years={s.annual.years}
              values={s.annual.revenue}
              fmt={(n) => big(n)}
            />
            <TrendBars
              label="Earnings per share"
              years={s.annual.years}
              values={s.annual.eps}
              fmt={(n) => num(n)}
            />
          </div>
        </Panel>

        {/* 8 Filings */}
        <Panel number={8} id="filings" title="Recent filings" className="filings-panel" bodyClass="flush">
          {s.filings.length === 0 && <div className="empty-row">No filings on record</div>}
          {s.filings.map((f) => (
            <a key={f.url} className="filing" href={f.url} target="_blank" rel="noreferrer">
              <span>
                <span className="filing-form">{f.form.startsWith("4") ? `FORM ${f.form}` : f.form}</span>
                <span className="filing-title">{f.title}</span>
              </span>
              <span className="filing-date">{f.filed_at}</span>
            </a>
          ))}
        </Panel>
      </div>

      <footer className="sources">
        <span>
          Fundamentals: SEC EDGAR
          {s.sources.fundamentals.form
            ? `, through ${s.sources.fundamentals.form} filed ${s.sources.fundamentals.through}`
            : ""}
        </span>
        <span>{demo ? "Quote and chart: made up for the demo" : `Quote: Finnhub, ${ago(s.sources.quote.fetched_at)}`}</span>
        <span>
          Chart: Alpaca, SIP feed
          {s.sources.prices.last_date ? `, closes through ${s.sources.prices.last_date}` : ""}
        </span>
        <span>Ratios computed locally from filings</span>
        <span>
          Charting by{" "}
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
            TradingView Lightweight Charts
          </a>
        </span>
      </footer>
    </div>
  );
}

function Stat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className="stat-value num">{value}</div>
    </div>
  );
}

function RangeBar({ low, high, value }: { low?: number | null; high?: number | null; value?: number | null }) {
  const pos =
    low != null && high != null && value != null && high > low
      ? Math.min(Math.max((value - low) / (high - low), 0), 1) * 100
      : null;
  return (
    <div className="range52 num">
      <span>{num(low)}</span>
      <span aria-hidden="true" className="range52-track">
        <span className="range52-line" />
        {pos != null && <span className="range52-mark" style={{ left: `${pos}%` }} />}
      </span>
      <span>{num(high)}</span>
    </div>
  );
}

const LYNCH_CATEGORIES = ["Slow grower", "Stalwart", "Fast grower", "Cyclical", "Turnaround", "Asset play"];

const TEST_ORDER = [
  "peg",
  "pe",
  "eps_growth",
  "revenue_holding",
  "debt_to_equity",
  "net_cash",
  "inventory",
  "insiders",
  "market_cap",
];

const PILL: Record<LynchTest["status"], string> = {
  pass: "pill pill-pass",
  watch: "pill pill-watch",
  fail: "pill pill-fail",
  missing: "pill pill-pending",
};

function LynchPanel({ lynch }: { lynch: Lynch | null }) {
  // The mockup's order, which pairs related tests across the two columns.
  const tests = [...(lynch?.tests ?? [])].sort((a, b) => TEST_ORDER.indexOf(a.key) - TEST_ORDER.indexOf(b.key));
  const available = tests.filter((t) => t.status !== "missing").reduce((a, t) => a + t.weight, 0);
  const earned = tests.reduce((a, t) => a + t.points, 0);
  const skipped = tests.filter((t) => t.status === "missing").length;
  return (
    <Panel
      number={2}
      id="lynch"
      title="Lynch check"
      right={
        <span className="panel-right">
          {lynch ? `${lynch.passed} of ${lynch.counted} tests passed` : "No data"}
        </span>
      }
      bodyClass="lynch-body"
    >
      <div className="lynch-score">
        <div className="score-line">
          <span className={lynch?.score != null ? "score" : "score score-pending"}>
            {lynch?.score != null ? Math.round(lynch.score) : DASH}
          </span>
          <span className="muted-caps">out of 100</span>
        </div>
        <div className="chips">
          {LYNCH_CATEGORIES.map((c) => (
            <span key={c} className={lynch?.category === c ? "chip chip-on-static" : "chip"}>
              {c}
            </span>
          ))}
        </div>
        {lynch && (
          <p className="score-math">
            {earned % 1 ? earned.toFixed(1) : earned} of {available} points
            {skipped ? `, ${skipped} test${skipped > 1 ? "s" : ""} without data left out` : ""}, scaled to
            100. A pass earns the full weight, a watch half.
          </p>
        )}
      </div>
      <div className="lynch-tests">
        {(tests.length ? tests : LYNCH_EMPTY).map((t) => (
          <div key={t.key} className="lynch-test" title={`${t.rule}. Weight ${t.weight}.`}>
            <span className="lynch-test-label">{t.label}</span>
            <span className={t.status === "missing" ? "lynch-test-value muted" : "lynch-test-value"}>
              {t.value ?? DASH}
            </span>
            <span className={PILL[t.status]}>{t.status === "missing" ? "No data" : t.status}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

const LYNCH_EMPTY: LynchTest[] = [
  "PEG under 1.0",
  "EPS growth above 15%",
  "P/E between 5 and 25",
  "Revenue growth holding up",
  "Debt to equity under 0.5",
  "Inventory slower than sales",
  "Insider buying, 6 months",
  "Market cap 300M to 10B",
  "Net cash is positive",
].map((label) => ({ key: label, label, value: null, status: "missing", weight: 0, points: 0, rule: "" }));

function TrendBars({
  label,
  years,
  values,
  fmt,
}: {
  label: string;
  years: number[];
  values: (number | null)[];
  fmt: (n: number | null) => string;
}) {
  const present = values.filter((v): v is number => v != null);
  const max = Math.max(...present.map(Math.abs), 0);
  const first = values.find((v) => v != null) ?? null;
  const last = [...values].reverse().find((v) => v != null) ?? null;
  return (
    <div className="trend-col">
      <div className="trend-head">
        <span className="muted-caps strong">{label}</span>
        <span className="trend-range num">
          {present.length ? `${fmt(first)} to ${fmt(last)}` : DASH}
        </span>
      </div>
      <div className="trend-bars" aria-hidden="true">
        {values.map((v, i) => (
          <div
            key={years[i]}
            className="trend-bar"
            title={`FY${years[i]}: ${fmt(v)}`}
            style={{
              height: v != null && max > 0 ? `${Math.max((Math.abs(v) / max) * 100, 2)}%` : "2px",
              background:
                v == null
                  ? "transparent"
                  : v < 0
                    ? "var(--down)"
                    : i === values.length - 1
                      ? "var(--accent)"
                      : "var(--border-strong)",
            }}
          />
        ))}
      </div>
      <div className="trend-years" aria-hidden="true">
        <span>{years.length ? `FY${String(years[0]).slice(2)}` : ""}</span>
        <span>{years.length ? `FY${String(years[years.length - 1]).slice(2)}` : ""}</span>
      </div>
    </div>
  );
}

function SkeletonBody() {
  return (
    <div className="body">
      <section className="stock-head skeleton" style={{ height: 96 }} />
      <section className="panel skeleton" style={{ height: 620 }} />
    </div>
  );
}
