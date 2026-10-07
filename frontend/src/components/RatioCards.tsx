import type { Ratios } from "../api";
import { DASH, num, pct, signedPct, times, tone } from "../format";
import { Panel } from "./Panel";

type Row = { label: string; key: string; fmt: (n: number | null | undefined) => string };

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

function RangeCard({ n, id, title, rows, r }: { n: number; id: string; title: string; rows: Row[]; r: Ratios }) {
  return (
    <Panel number={n} id={id} title={title} className="card" bodyClass="card-body">
      <div className="ratio-grid ratio-head">
        <div>Metric</div>
        <div className="right">Now</div>
        <div className="range-col">5-yr range</div>
        <div className="right">Sector</div>
      </div>
      {rows.map((row) => (
        <div key={row.key} className="ratio-grid ratio-row">
          <div className="row-label">{row.label}</div>
          <div className="right strong num">{row.fmt(r[row.key])}</div>
          {/* Range position and sector median arrive in phase 5. */}
          <div className="range-col" aria-hidden="true" title="5-year range arrives in phase 5">
            <div className="rbar">
              <div className="rbar-track pending" />
            </div>
          </div>
          <div className="right muted num" title="Sector medians arrive in phase 5">
            {DASH}
          </div>
        </div>
      ))}
    </Panel>
  );
}

function GrowthCard({ r }: { r: Ratios }) {
  return (
    <Panel number={4} id="growth" title="Growth" className="card" bodyClass="card-body">
      <div className="growth-grid ratio-head">
        <div>Per year</div>
        <div className="right">1 yr</div>
        <div className="right">3 yr</div>
        <div className="right">5 yr</div>
        <div className="right">Sector</div>
      </div>
      {GROWTH.map((g) => (
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
          <div className="right muted num" title="Sector medians arrive in phase 5">
            {DASH}
          </div>
        </div>
      ))}
    </Panel>
  );
}

export function RatioCards({ ratios }: { ratios: Ratios }) {
  return (
    <>
      <div className="cards">
        <RangeCard n={3} id="valuation" title="Valuation" rows={VALUATION} r={ratios} />
        <GrowthCard r={ratios} />
        <RangeCard n={5} id="quality" title="Quality" rows={QUALITY} r={ratios} />
        <RangeCard n={6} id="balance" title="Balance sheet" rows={BALANCE} r={ratios} />
      </div>
      <div className="card-legend">
        <span>
          <i className="swatch" style={{ background: "var(--accent)", width: 6 }} />
          Today, inside the stock's own 5-year low to high
        </span>
        <span>
          <i className="swatch" style={{ background: "var(--muted)", width: 2 }} />
          Sector median
        </span>
        <span className="pending-note">Ranges and sector medians arrive in phase 5</span>
      </div>
    </>
  );
}
