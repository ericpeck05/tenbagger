import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import {
  type AllocRow,
  api,
  type Holding,
  keys,
  type PerfRange,
  type Portfolio,
  type Transaction,
} from "../api";
import { Panel } from "../components/Panel";
import { PerformanceChart } from "../components/PerformanceChart";
import { TradeForm } from "../components/TradeForm";
import { DASH, num, pct, signed, signedPct, signedPctPoints, tone } from "../format";
import { useHotkeys } from "../hooks/useHotkeys";
import { jumpTo, PORTFOLIO_PANELS } from "../panels";
import { navigate, stockPath } from "../router";

const RANGES: PerfRange[] = ["1M", "6M", "YTD", "1Y", "ALL"];
const RANGE_WORDS: Record<PerfRange, string> = {
  "1M": "1 month",
  "6M": "6 months",
  YTD: "year to date",
  "1Y": "1 year",
  ALL: "since the first trade",
};

export function PortfolioPage() {
  const [range, setRange] = useState<PerfRange>("1Y");
  const [form, setForm] = useState<{ editing: Transaction | null } | null>(null);
  const [showAll, setShowAll] = useState(false);

  const pf = useQuery({ queryKey: keys.portfolio, queryFn: api.portfolio, refetchInterval: 60_000 });
  const perf = useQuery({
    queryKey: keys.performance(range),
    queryFn: () => api.performance(range),
    placeholderData: keepPreviousData,
  });
  const log = useQuery({ queryKey: keys.transactions, queryFn: api.transactions, enabled: showAll });

  useHotkeys(
    useCallback((e: KeyboardEvent) => {
      const panel = PORTFOLIO_PANELS.find((p) => String(p.n) === e.key);
      if (panel) {
        jumpTo(panel.id);
        return true;
      }
      if (e.key === "t" || e.key === "T") {
        setForm({ editing: null });
        return true;
      }
      return false;
    }, []),
  );

  const p = pf.data;
  const s = p?.summary;
  const vsBench =
    s?.return_1y != null && s.benchmark_1y != null ? (s.return_1y - s.benchmark_1y) * 100 : null;

  return (
    <main className="portfolio">
      <section className="stock-head">
        <div className="stock-id">
          <div className="stock-title">
            <h1 className="caps-title">Portfolio</h1>
            <span className="company">Main account</span>
            <span className="chip">
              {s ? `${s.positions} position${s.positions === 1 ? "" : "s"}` : DASH}
            </span>
          </div>
          <div className="stock-price">
            <span className="price num">{s ? num(s.value) : DASH}</span>
            {s && s.positions > 0 && (
              <span className={`day-change num ${tone(s.day_change)}`}>
                {signed(s.day_change)} {signedPct(s.day_change_pct, 2)}
              </span>
            )}
            <span className="price-note">USD, today</span>
          </div>
        </div>
        <div className="head-right">
          <div className="stat-strip">
            <Stat label="Total gain" value={signed(s?.gain)} cls={tone(s?.gain)} />
            <Stat label="Gain %" value={signedPct(s?.gain_pct)} cls={tone(s?.gain_pct)} />
            <Stat label="Cost basis" value={num(s?.cost_basis)} />
            <Stat label="Cash" value={num(s?.cash)} />
            <Stat
              label="1Y vs benchmark"
              value={vsBench == null ? DASH : `${signed(vsBench, 1)} pts`}
              cls={tone(vsBench)}
              title={
                s?.return_1y != null
                  ? `Portfolio ${signedPct(s.return_1y)} against SPY ${signedPct(s.benchmark_1y)} since ${s.return_since}`
                  : "Needs at least two days of history"
              }
            />
          </div>
          <button type="button" className="btn btn-primary btn-tall" onClick={() => setForm({ editing: null })}>
            Add trade <span className="key-inline">T</span>
          </button>
        </div>
      </section>

      {p && p.summary.trades === 0 && (
        <div className="notice">
          No trades yet. Press <span className="key">T</span> or Add trade to log a buy, sell, deposit,
          withdrawal, or dividend. Trades stay on this computer.
        </div>
      )}

      <div className="two-up">
        <Panel
          number={1}
          id="performance"
          title="Performance"
          className="perf-panel"
          note={<span className="panel-note">Return, {RANGE_WORDS[range]}</span>}
          right={
            <div role="group" aria-label="Chart range" className="seg">
              {RANGES.map((r) => (
                <button
                  key={r}
                  type="button"
                  aria-pressed={range === r}
                  className={range === r ? "seg-btn on" : "seg-btn"}
                  onClick={() => setRange(r)}
                >
                  {r}
                </button>
              ))}
            </div>
          }
          bodyClass="price-body"
        >
          <div className="ohlc">
            <span className="series-key">
              <i className="line-solid" />
              Portfolio{" "}
              <span className={`num ${tone(perf.data?.portfolio_return)}`}>
                {signedPct(perf.data?.portfolio_return)}
              </span>
            </span>
            <span className="series-key">
              <i className="line-dashed" />
              Benchmark, {perf.data?.benchmark ?? "SPY"}{" "}
              <span className={`num ${tone(perf.data?.benchmark_return)}`}>
                {signedPct(perf.data?.benchmark_return)}
              </span>
            </span>
          </div>
          <PerformanceChart data={perf.data} />
        </Panel>

        <Panel number={2} id="allocation" title="Allocation" className="alloc-panel" bodyClass="alloc-body">
          <div>
            <div className="alloc-head">
              By Lynch category <span className="pending-note">Categories arrive in phase 5</span>
            </div>
            {(p?.allocation.kinds ?? []).map((k) => (
              <AllocBar key={k.name} row={k} grey={k.name !== "Stocks"} />
            ))}
          </div>
          <div>
            <div className="alloc-head">Stocks by sector</div>
            {p && p.allocation.by_sector.length === 0 && <div className="empty-row">No stocks held</div>}
            {(p?.allocation.by_sector ?? []).map((k) => (
              <AllocBar key={k.name} row={k} />
            ))}
          </div>
        </Panel>
      </div>

      <HoldingsTable p={p} />

      <div className="three-up">
        <Panel number={4} id="lookthrough" title="Look-through" className="third">
          <div className="tiles">
            {["P/E", "EPS growth", "PEG", "Lynch score", "Largest stock", "Below cost"].map((t) => (
              <div key={t} className="tile">
                <div className="tile-label">{t}</div>
                <div className="tile-value muted">{DASH}</div>
              </div>
            ))}
          </div>
          <p className="fine">
            The stocks treated as one company, weighted by value. Index funds and cash are left out.{" "}
            <span className="pending-note">Arrives in phase 5</span>
          </p>
        </Panel>

        <Panel
          number={5}
          id="activity"
          title="Activity"
          className="third"
          bodyClass="flush"
          right={
            p && p.summary.trades > p.activity.length ? (
              <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Latest only" : `All ${p.summary.trades}`}
              </button>
            ) : undefined
          }
        >
          {p && p.activity.length === 0 && <div className="empty-row">No activity yet</div>}
          <div className={showAll ? "activity-scroll" : undefined}>
            {(showAll && log.data ? log.data : (p?.activity ?? [])).map((t) => (
              <ActivityRow key={t.id} t={t} onEdit={() => setForm({ editing: t })} />
            ))}
          </div>
        </Panel>

        <Panel number={6} id="filings" title="Filings from your holdings" className="third" bodyClass="flush">
          {p && p.filings.length === 0 && <div className="empty-row">No filings yet</div>}
          {(p?.filings ?? []).map((f) => (
            <a key={`${f.ticker}-${f.url}`} className="pf-filing" href={f.url} target="_blank" rel="noreferrer">
              <span className="muted num">{f.filed_at}</span>
              <span className="strong">{f.ticker}</span>
              <span className="filing-form">{f.form.startsWith("4") ? `FORM ${f.form}` : f.form}</span>
              <span className="filing-title ellipsis">{f.title}</span>
            </a>
          ))}
        </Panel>
      </div>

      <footer className="sources">
        <span>Trades are stored on this computer only</span>
        <span>Quotes: Finnhub</span>
        <span>History: Alpaca, SIP feed</span>
        <span>Returns are time-weighted and exclude dividends unless logged</span>
        <span>Benchmark: SPY</span>
      </footer>

      {form && <TradeForm editing={form.editing} onClose={() => setForm(null)} />}
    </main>
  );
}

function Stat({ label, value, cls, title }: { label: string; value: string; cls?: string; title?: string }) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value num ${cls ?? ""}`}>{value}</div>
    </div>
  );
}

function AllocBar({ row, grey }: { row: AllocRow; grey?: boolean }) {
  return (
    <div className="alloc-row">
      <span className={grey ? "row-label muted-2" : "row-label"}>{row.name}</span>
      <span aria-hidden="true" className="alloc-track">
        <span
          style={{
            width: `${Math.min(Math.max(row.weight, 0), 1) * 100}%`,
            background: grey ? "#6A6A6A" : "var(--accent)",
          }}
        />
      </span>
      <span className="right strong num">{pct(row.weight)}</span>
    </div>
  );
}

type SortKey = keyof Pick<
  Holding,
  "ticker" | "shares" | "avg_cost" | "price" | "day_change_pct" | "value" | "gain" | "gain_pct" | "weight" | "pe" | "peg"
>;

const COLUMNS: { key: SortKey | null; label: string; right?: boolean }[] = [
  { key: "ticker", label: "Position" },
  { key: "shares", label: "Shares", right: true },
  { key: "avg_cost", label: "Avg cost", right: true },
  { key: "price", label: "Price", right: true },
  { key: "day_change_pct", label: "Day", right: true },
  { key: "value", label: "Value", right: true },
  { key: "gain", label: "Gain", right: true },
  { key: "gain_pct", label: "Gain %", right: true },
  { key: "weight", label: "Weight" },
  { key: null, label: "Category" },
  { key: null, label: "Lynch", right: true },
  { key: "pe", label: "P/E", right: true },
  { key: "peg", label: "PEG", right: true },
];

function HoldingsTable({ p }: { p: Portfolio | undefined }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "value", desc: true });
  const rows = useMemo(() => {
    const list = [...(p?.holdings ?? [])];
    list.sort((a, b) => {
      const x = a[sort.key];
      const y = b[sort.key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
      return sort.desc ? -c : c;
    });
    return list;
  }, [p, sort]);
  const s = p?.summary;
  const maxWeight = Math.max(...rows.map((r) => r.weight ?? 0), s && s.value ? s.cash / s.value : 0, 0.0001);

  return (
    <Panel
      number={3}
      id="holdings"
      title="Holdings"
      right={<span className="panel-right muted">Click a column to sort</span>}
      bodyClass="flush-x"
    >
      <div className="table-scroll">
        <div className="holdings">
          <div className="h-grid h-head" role="row">
            {COLUMNS.map((c) => (
              <button
                key={c.label}
                type="button"
                className={`h-th ${c.right ? "right" : ""} ${sort.key === c.key ? "sorted" : ""}`}
                disabled={!c.key}
                onClick={() =>
                  c.key && setSort((cur) => ({ key: c.key!, desc: cur.key === c.key ? !cur.desc : c.key !== "ticker" }))
                }
              >
                {c.label}
                {sort.key === c.key ? (sort.desc ? " ▼" : " ▲") : ""}
              </button>
            ))}
          </div>
          {rows.map((h) => (
            <a
              key={h.ticker}
              className={h.is_company ? "h-grid h-row" : "h-grid h-row h-fund"}
              href={h.is_company ? stockPath(h.ticker) : undefined}
              onClick={(e) => {
                if (!h.is_company) return;
                e.preventDefault();
                navigate(stockPath(h.ticker));
              }}
            >
              <div className="ellipsis">
                <span className="h-ticker">{h.ticker}</span>
                <span className="h-name">{h.name}</span>
              </div>
              <div className="right num">{num(h.shares, h.shares % 1 ? 3 : 0)}</div>
              <div className="right num muted-2">{num(h.avg_cost)}</div>
              <div className="right num">{num(h.price)}</div>
              <div className={`right num ${tone(h.day_change_pct)}`}>{signedPctPoints(h.day_change_pct)}</div>
              <div className="right num strong">{num(h.value)}</div>
              <div className={`right num ${tone(h.gain)}`}>{signed(h.gain)}</div>
              <div className={`right num ${tone(h.gain_pct)}`}>{signedPct(h.gain_pct)}</div>
              <WeightBar weight={h.weight} max={maxWeight} grey={!h.is_company} />
              <div className="h-cat">{h.category ?? DASH}</div>
              <div className="right num muted">{DASH}</div>
              <div className="right num">{num(h.pe, 1)}</div>
              <div className="right num">{num(h.peg, 2)}</div>
            </a>
          ))}
          {s && (
            <div className="h-grid h-row h-cash">
              <div>
                <span className="h-ticker">CASH</span>
                <span className="h-name">Uninvested</span>
              </div>
              <div />
              <div />
              <div />
              <div />
              <div className="right num strong text">{num(s.cash)}</div>
              <div />
              <div />
              <WeightBar weight={s.value ? s.cash / s.value : null} max={maxWeight} grey />
              <div />
              <div />
              <div />
              <div />
            </div>
          )}
          {s && (
            <div className="h-grid h-total">
              <div className="caps-accent">Total</div>
              <div />
              <div className="right num">{num(s.cost_basis)}</div>
              <div />
              <div className={`right num ${tone(s.day_change_pct)}`}>{signedPct(s.day_change_pct, 2)}</div>
              <div className="right num">{num(s.value)}</div>
              <div className={`right num ${tone(s.gain)}`}>{signed(s.gain)}</div>
              <div className={`right num ${tone(s.gain_pct)}`}>{signedPct(s.gain_pct)}</div>
              <div className="right num">100%</div>
              <div />
              <div className="right num muted">{DASH}</div>
              <div className="right num muted">{DASH}</div>
              <div className="right num muted">{DASH}</div>
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}

function WeightBar({ weight, max, grey }: { weight: number | null; max: number; grey?: boolean }) {
  return (
    <div className="weight">
      <span aria-hidden="true" className="weight-track">
        <span
          style={{
            width: `${weight ? (weight / max) * 100 : 0}%`,
            background: grey ? "#6A6A6A" : "var(--accent)",
          }}
        />
      </span>
      <span className="num">{pct(weight)}</span>
    </div>
  );
}

const TYPE_STYLE: Record<string, string> = {
  buy: "pill-up",
  sell: "pill-down",
  deposit: "pill-cash",
  withdrawal: "pill-cash",
  dividend: "pill-cash",
};

function ActivityRow({ t, onEdit }: { t: Transaction; onEdit: () => void }) {
  const label = t.type === "buy" || t.type === "sell" ? t.type.toUpperCase() : "CASH";
  const what =
    t.type === "buy" || t.type === "sell" ? (
      <>
        <span className="strong">{t.ticker}</span> {num(t.shares, t.shares && t.shares % 1 ? 3 : 0)} @{" "}
        {num(t.price)}
      </>
    ) : (
      <>
        {t.type === "deposit" ? "Deposit" : t.type === "withdrawal" ? "Withdrawal" : "Dividend"}
        {t.ticker ? <span className="strong"> {t.ticker}</span> : null}
      </>
    );
  return (
    <button type="button" className="activity" onClick={onEdit} title="Edit or delete">
      <span className="muted num">{t.date}</span>
      <span className={`pill pill-sm ${TYPE_STYLE[t.type]}`}>{label}</span>
      <span className="ellipsis">{what}</span>
      <span className="right num">{num(t.amount)}</span>
    </button>
  );
}
