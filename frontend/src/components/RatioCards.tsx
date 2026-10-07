import type { Ranges, Ratios, Stock } from "../api";
import { DASH, num, pct, signedPct, times, tone } from "../format";
import { Panel } from "./Panel";

type Fmt = (n: number | null | undefined) => string;
type Row = { label: string; key: string; fmt: Fmt };

const VALUATION: Row[] = [
  { label: "P/E, trailing", key: "pe", fmt: (n) => num(n, 1) },
  { label: "PEG", key: "peg", fmt: (n) => num(n, 2) },
  { label: "Price to sales", key: "price_to_sales", fmt: (n) => num(n, 2) },
  { label: "Price to book", key: "price_to_book", fmt: (n) => num(n, 1) },
  { label: "EV / EBITDA", key: "ev_ebitda", fmt: (n) => num(n, 1) },
  { label: "Free cash flow yield", key: "fcf_yield", fmt: (n) => pct(n, 1) },
];

const QUALITY: Row[] = [
  { label: "Gross margin", key: "gross_margin", fmt: (n) => pct(n, 1) },
  { label: "Operating margin", key: "operating_margin", fmt: (n) => pct(n, 1) },
  { label: "Net margin", key: "net_margin", fmt: (n) => pct(n, 1) },
  { label: "Return on equity", key: "roe", fmt: (n) => pct(n, 1) },
  { label: "Return on invested capital", key: "roic", fmt: (n) => pct(n, 1) },
  { label: "Cash conversion", key: "cash_conversion", fmt: (n) => pct(n, 0) },
];

const BALANCE: Row[] = [
  { label: "Debt to equity", key: "debt_to_equity", fmt: (n) => num(n, 2) },
  { label: "Net cash per share", key: "net_cash_per_share", fmt: (n) => num(n, 2) },
  { label: "Net debt / EBITDA", key: "net_debt_ebitda", fmt: (n) => times(n, 1) },
  { label: "Current ratio", key: "current_ratio", fmt: (n) => num(n, 1) },
  { label: "Interest coverage", key: "interest_coverage", fmt: (n) => times(n, 1) },
  { label: "Inventory turnover", key: "inventory_turnover", fmt: (n) => times(n, 1) },
];

const GROWTH = [
  { label: "Revenue", key: "revenue" },
  { label: "Earnings per share", key: "eps" },
  { label: "Free cash flow", key: "fcf" },
  { label: "Book value per share", key: "bvps" },
  { label: "Inventory", key: "inventory" },
  { label: "Share count", key: "shares" },
];

type Medians = Stock["sector_medians"];

/** Where a value sits between low and high, as a percent of the bar, kept on the bar. */
function place(v: number | null | undefined, low: number, high: number): number | null {
  if (v == null) return null;
  if (high === low) return 50;
  return Math.min(Math.max(((v - low) / (high - low)) * 100, 0), 100);
}

function RangeBar({ value, median, range, fmt, years }: {
  value: number | null | undefined;
  median: number | null | undefined;
  range: Ranges["metrics"][string] | undefined;
  fmt: Fmt;
  years: number[];
}) {
  if (!range || range.low == null || range.high == null) {
    return (
      <div className="range-col" aria-hidden="true" title="Not enough history for a 5-year range">
        <div className="rbar">
          <div className="rbar-track pending" />
        </div>
      </div>
    );
  }
  // The bar spans the 5-year low to high. Today or the sector median can sit outside it;
  // they are drawn at the end, and the tooltip gives the real numbers.
  const pos = place(value, range.low, range.high);
  const sec = place(median, range.low, range.high);
  const history = range.values
    .map((v, i) => `FY${years[i]}: ${fmt(v)}`)
    .join(", ");
  return (
    <div
      className="range-col"
      title={`5-year range ${fmt(range.low)} to ${fmt(range.high)} (${history}). Today ${fmt(value)}${
        median != null ? `, sector median ${fmt(median)}` : ""
      }`}
    >
      <div className="rbar" aria-hidden="true">
        <div className="rbar-track" />
        {sec != null && <div className="rbar-sector" style={{ left: `${sec}%` }} />}
        {pos != null && <div className="rbar-now" style={{ left: `${pos}%` }} />}
      </div>
    </div>
  );
}

function RangeCard({ n, id, title, rows, r, ranges, medians }: {
  n: number;
  id: string;
  title: string;
  rows: Row[];
  r: Ratios;
  ranges: Ranges;
  medians: Medians;
}) {
  return (
    <Panel number={n} id={id} title={title} className="card" bodyClass="card-body">
      <div className="ratio-grid ratio-head">
        <div>Metric</div>
        <div className="right">Now</div>
        <div className="range-col">5-yr range</div>
        <div className="right">Sector</div>
      </div>
      {rows.map((row) => {
        const median = medians?.[row.key];
        return (
          <div key={row.key} className="ratio-grid ratio-row">
            <div className="row-label">{row.label}</div>
            <div className="right strong num">{row.fmt(r[row.key])}</div>
            <RangeBar
              value={r[row.key]}
              median={median?.value}
              range={ranges.metrics[row.key]}
              fmt={row.fmt}
              years={ranges.years}
            />
            <div
              className="right muted num"
              title={median ? `Median of ${median.companies} companies above $300M` : undefined}
            >
              {median?.value != null ? row.fmt(median.value) : DASH}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

function GrowthCard({ r, medians }: { r: Ratios; medians: Medians }) {
  return (
    <Panel number={4} id="growth" title="Growth" className="card" bodyClass="card-body">
      <div className="growth-grid ratio-head">
        <div>Per year</div>
        <div className="right">1 yr</div>
        <div className="right">3 yr</div>
        <div className="right">5 yr</div>
        <div className="right">Sector</div>
      </div>
      {GROWTH.map((g) => {
        const median = medians?.[`${g.key}_growth_5y`]?.value;
        return (
          <div key={g.key} className="growth-grid ratio-row">
            <div className="row-label">{g.label}</div>
            {[1, 3, 5].map((y) => {
              const v = r[`${g.key}_growth_${y}y`];
              return (
                <div key={y} className={`right strong num ${tone(v)}`}>
                  {signedPct(v, 1)}
                </div>
              );
            })}
            <div className="right muted num" title="Sector median of the 5-year rate">
              {median != null ? signedPct(median, 1) : DASH}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

export function RatioCards({ stock }: { stock: Stock }) {
  const r = stock.ratios ?? {};
  const medians = stock.sector_medians;
  const ranges = stock.ranges_5y;
  return (
    <>
      <div className="cards">
        <RangeCard n={3} id="valuation" title="Valuation" rows={VALUATION} r={r} ranges={ranges} medians={medians} />
        <GrowthCard r={r} medians={medians} />
        <RangeCard n={5} id="quality" title="Quality" rows={QUALITY} r={r} ranges={ranges} medians={medians} />
        <RangeCard n={6} id="balance" title="Balance sheet" rows={BALANCE} r={r} ranges={ranges} medians={medians} />
      </div>
      <div className="card-legend">
        <span>
          <i className="swatch" style={{ background: "var(--accent)", width: 6 }} />
          Today, inside the stock's own 5-year low to high
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--muted)", width: 2 }} />
          Sector median{stock.sector ? `, ${stock.sector}` : ""}
        </span>
      </div>
    </>
  );
}
