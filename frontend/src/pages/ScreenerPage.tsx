import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  type FieldKind,
  type SavedScreen,
  type ScreenField,
  type ScreenOp,
  type ScreenQuery,
  type ScreenRow,
} from "../api";
import { Panel } from "../components/Panel";
import { big, DASH, num, pct, signedPct, signedPctPoints, times, tone } from "../format";
import { usePrefetchStock } from "../hooks/usePrefetchStock";
import { useHotkeys } from "../hooks/useHotkeys";
import { jumpTo } from "../panels";
import { navigate, stockPath } from "../router";

/** One filter as the page edits it: values are strings in display units (15 for 15%). */
type Filter = { key: string; op: ScreenOp; values: [string, string] };
type State = {
  filters: Filter[];
  sectors: string[];
  categories: string[];
  sort: string;
  dir: "asc" | "desc";
};

const PAGE = 100;
const EMPTY: State = { filters: [], sectors: [], categories: [], sort: "market_cap", dir: "desc" };

// ---------------------------------------------------------------- units

/** Display value to stored value: "15" -> 0.15 for percentages, "300M" -> 3e8 for money. */
function toStored(text: string, kind: FieldKind): number | null {
  const t = text.trim().replace(/,/g, "").replace(/%$/, "").toUpperCase();
  if (!t) return null;
  const m = /^(-?\d*\.?\d+)\s*([KMBT]?)$/.exec(t);
  if (!m) return null;
  const n = Number(m[1]) * ({ K: 1e3, M: 1e6, B: 1e9, T: 1e12 }[m[2] as "K"] ?? 1);
  return kind === "pct" ? n / 100 : n;
}

function toDisplay(v: number, kind: FieldKind): string {
  if (kind === "pct") return String(Number((v * 100).toFixed(4)));
  if (kind === "money") {
    for (const [div, unit] of [
      [1e12, "T"],
      [1e9, "B"],
      [1e6, "M"],
    ] as const) {
      if (Math.abs(v) >= div) return `${Number((v / div).toFixed(3))}${unit}`;
    }
  }
  return String(v);
}

function fmt(v: number | string | null | undefined, kind: FieldKind | undefined): string {
  if (v == null || typeof v === "string") return v ?? DASH;
  switch (kind) {
    case "pct":
      return pct(v, 1);
    case "money":
      return big(v);
    case "times":
      return times(v, 1);
    case "score":
      return String(Math.round(v));
    case "price":
      return num(v, 2);
    default:
      return num(v, 2);
  }
}

// ---------------------------------------------------------------- URL state

function fromQuery(q: ScreenQuery, fields: Map<string, ScreenField>): State {
  return {
    filters: q.filters.map(([key, op, value]) => {
      const kind = fields.get(key)?.kind ?? "ratio";
      const vals = Array.isArray(value) ? value : [value];
      const simple: ScreenOp = op === "gte" ? "gt" : op === "lte" ? "lt" : op;
      return {
        key,
        op: simple,
        values: [toDisplay(vals[0]!, kind), vals[1] != null ? toDisplay(vals[1], kind) : ""],
      };
    }),
    sectors: q.sectors ?? [],
    categories: q.categories ?? [],
    sort: q.sort ?? "market_cap",
    dir: q.dir ?? "desc",
  };
}

function toQuery(s: State, fields: Map<string, ScreenField>): ScreenQuery {
  const filters: ScreenQuery["filters"] = [];
  for (const f of s.filters) {
    const kind = fields.get(f.key)?.kind ?? "ratio";
    const a = toStored(f.values[0], kind);
    const b = toStored(f.values[1], kind);
    if (f.op === "between") {
      if (a != null && b != null) filters.push([f.key, "between", [a, b]]);
    } else if (a != null) {
      filters.push([f.key, f.op, a]);
    }
  }
  return { filters, sectors: s.sectors, categories: s.categories, sort: s.sort, dir: s.dir };
}

function toParams(q: ScreenQuery, limit: number): string {
  const p = new URLSearchParams();
  for (const [key, op, v] of q.filters) p.append("f", `${key}:${op}:${Array.isArray(v) ? v.join(",") : v}`);
  q.sectors?.forEach((x) => p.append("sector", x));
  q.categories?.forEach((x) => p.append("category", x));
  p.set("sort", q.sort ?? "market_cap");
  p.set("dir", q.dir ?? "desc");
  p.set("limit", String(limit));
  return p.toString();
}

function readUrl(): ScreenQuery | null {
  const raw = new URLSearchParams(window.location.search).get("q");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ScreenQuery;
  } catch {
    return null;
  }
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

// ---------------------------------------------------------------- page

export function ScreenerPage() {
  const meta = useQuery({ queryKey: ["screener-fields"], queryFn: api.screenerFields, staleTime: Infinity });
  const screens = useQuery({ queryKey: ["screens"], queryFn: api.screens });
  if (!meta.data || !screens.data) return <main className="portfolio" />;
  return <Screener meta={meta.data} screens={screens.data} />;
}

type Meta = { fields: ScreenField[]; sectors: string[]; categories: string[] };

function Screener({ meta, screens }: { meta: Meta; screens: SavedScreen[] }) {
  const qc = useQueryClient();
  const fields = useMemo(() => new Map(meta.fields.map((f) => [f.key, f])), [meta]);

  // Start from the screen in the URL, else the Lynch preset.
  const [start] = useState(() => {
    const fromUrl = readUrl();
    const preset = screens.find((s) => s.builtin);
    const q = fromUrl ?? preset?.query;
    return { state: q ? fromQuery(q, fields) : EMPTY, active: fromUrl ? null : (preset?.id ?? null) };
  });
  const [state, setState] = useState<State | null>(start.state);
  const [limit, setLimit] = useState(PAGE);
  const [active, setActive] = useState<number | null>(start.active);

  const query = useMemo(() => (state ? toQuery(state, fields) : null), [state, fields]);
  const debounced = useDebounced(query, 250);

  useEffect(() => {
    if (!debounced) return;
    const url = `/screener?q=${encodeURIComponent(JSON.stringify(debounced))}`;
    window.history.replaceState(null, "", url);
  }, [debounced]);

  const results = useQuery({
    queryKey: ["screener", debounced, limit],
    queryFn: () => api.screener(toParams(debounced!, limit)),
    enabled: !!debounced,
    placeholderData: keepPreviousData,
  });

  const save = useMutation({
    mutationFn: (name: string) => api.saveScreen(name, query!),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["screens"] });
      setActive(s.id);
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteScreen(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["screens"] });
      setActive(null);
    },
  });

  useHotkeys(
    useCallback((e: KeyboardEvent) => {
      if (e.key === "1") jumpTo("filters");
      else if (e.key === "2") jumpTo("results");
      else return false;
      return true;
    }, []),
  );

  const update = (fn: (s: State) => State) => {
    setState((s) => (s ? fn(s) : s));
    setActive(null);
    setLimit(PAGE);
  };
  const apply = (screen: SavedScreen) => {
    setState(fromQuery(screen.query, fields));
    setActive(screen.id);
    setLimit(PAGE);
  };

  const r = results.data;
  const activeScreen = screens.find((s) => s.id === active);

  return (
    <main className="portfolio">
      <section className="stock-head">
        <div className="stock-id">
          <div className="stock-title">
            <h1 className="caps-title">Screener</h1>
            <span className="company">{activeScreen ? activeScreen.name : "Custom screen"}</span>
            <span className="chip num">
              {r ? `${r.total.toLocaleString("en-US")} ${r.total === 1 ? "company" : "companies"}` : DASH}
            </span>
          </div>
        </div>
        <div className="head-right">
          {screens.map((s) => (
            <span key={s.id} className="screen-chip">
              <button
                type="button"
                className={s.id === active ? "chip chip-btn chip-on" : "chip chip-btn"}
                onClick={() => apply(s)}
              >
                {s.name}
              </button>
              {!s.builtin && s.id === active && (
                <button
                  type="button"
                  className="link-btn"
                  title="Delete this saved screen"
                  onClick={() => remove.mutate(s.id)}
                >
                  Delete
                </button>
              )}
            </span>
          ))}
          <button
            type="button"
            className="btn"
            onClick={() => {
              const name = window.prompt("Name this screen");
              if (name?.trim()) save.mutate(name.trim());
            }}
          >
            Save screen
          </button>
        </div>
      </section>

      {state && (
        <Panel
          number={1}
          id="filters"
          title="Filters"
          right={
            <button type="button" className="link-btn" onClick={() => update(() => EMPTY)}>
              Clear all
            </button>
          }
          bodyClass="filters-body"
        >
          {state.filters.map((f, i) => (
            <FilterRow
              key={i}
              f={f}
              fields={meta.fields}
              onChange={(nf) => update((s) => ({ ...s, filters: s.filters.map((x, j) => (j === i ? nf : x)) }))}
              onRemove={() => update((s) => ({ ...s, filters: s.filters.filter((_, j) => j !== i) }))}
            />
          ))}
          <div className="filter-actions">
            <button
              type="button"
              className="btn"
              onClick={() =>
                update((s) => ({ ...s, filters: [...s.filters, { key: "pe", op: "lt", values: ["", ""] }] }))
              }
            >
              Add filter
            </button>
            <span className="fine-inline">Percentages in %, money as 300M or 10B</span>
          </div>
          <ChipGroup
            label="Lynch category"
            options={meta.categories}
            selected={state.categories}
            onToggle={(c) =>
              update((s) => ({
                ...s,
                categories: s.categories.includes(c) ? s.categories.filter((x) => x !== c) : [...s.categories, c],
              }))
            }
          />
          <ChipGroup
            label="Sector"
            options={meta.sectors}
            selected={state.sectors}
            onToggle={(c) =>
              update((s) => ({
                ...s,
                sectors: s.sectors.includes(c) ? s.sectors.filter((x) => x !== c) : [...s.sectors, c],
              }))
            }
          />
        </Panel>
      )}

      <Panel
        number={2}
        id="results"
        title="Results"
        right={
          <span className="panel-right muted">
            {r ? `${Math.min(r.rows.length, r.total)} of ${r.total.toLocaleString("en-US")} shown` : ""}
          </span>
        }
        bodyClass="flush-x"
      >
        {state && r && (
          <ResultsTable
            r={r}
            fields={fields}
            sort={state.sort}
            dir={state.dir}
            onSort={(key) =>
              update((s) => ({
                ...s,
                sort: key,
                dir: s.sort === key ? (s.dir === "desc" ? "asc" : "desc") : key === "ticker" ? "asc" : "desc",
              }))
            }
          />
        )}
        {r && r.total > r.rows.length && (
          <div className="more">
            <button type="button" className="btn" onClick={() => setLimit((l) => Math.min(l + PAGE, 500))} disabled={limit >= 500}>
              {limit >= 500 ? "Showing the first 500, narrow the screen to see more" : `Show ${PAGE} more`}
            </button>
          </div>
        )}
      </Panel>

      <footer className="sources">
        <span>Every company in EDGAR's ticker list with reported financials</span>
        <span>Price-based ratios use the latest quote, or the latest close for cold stocks</span>
        <span>Missing values never match a filter</span>
      </footer>
    </main>
  );
}

function FilterRow({
  f,
  fields,
  onChange,
  onRemove,
}: {
  f: Filter;
  fields: ScreenField[];
  onChange: (f: Filter) => void;
  onRemove: () => void;
}) {
  const kind = fields.find((x) => x.key === f.key)?.kind;
  const unit = kind === "pct" ? "%" : kind === "money" ? "$" : "";
  return (
    <div className="filter-row">
      <select
        className="input"
        value={f.key}
        onChange={(e) => onChange({ ...f, key: e.target.value, values: ["", ""] })}
        aria-label="Metric"
      >
        {fields.map((x) => (
          <option key={x.key} value={x.key}>
            {x.label}
          </option>
        ))}
      </select>
      <select
        className="input"
        value={f.op}
        onChange={(e) => onChange({ ...f, op: e.target.value as ScreenOp })}
        aria-label="Comparison"
      >
        <option value="gt">above</option>
        <option value="lt">below</option>
        <option value="between">between</option>
      </select>
      <input
        className="input input-num"
        value={f.values[0]}
        placeholder={unit || "value"}
        inputMode="decimal"
        onChange={(e) => onChange({ ...f, values: [e.target.value, f.values[1]] })}
        aria-label="Value"
      />
      {f.op === "between" && (
        <>
          <span className="muted">and</span>
          <input
            className="input input-num"
            value={f.values[1]}
            placeholder={unit || "value"}
            inputMode="decimal"
            onChange={(e) => onChange({ ...f, values: [f.values[0], e.target.value] })}
            aria-label="Upper value"
          />
        </>
      )}
      <span className="muted unit">{kind === "pct" ? "%" : ""}</span>
      <button type="button" className="link-btn" onClick={onRemove} aria-label="Remove filter">
        Remove
      </button>
    </div>
  );
}

function ChipGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (o: string) => void;
}) {
  return (
    <div className="chip-group">
      <div className="alloc-head">
        {label}
        {selected.length ? `, ${selected.length} selected` : ", any"}
      </div>
      <div className="chips">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            aria-pressed={selected.includes(o)}
            className={selected.includes(o) ? "chip chip-btn chip-on" : "chip chip-btn"}
            onClick={() => onToggle(o)}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

const BASE_COLUMNS = ["lynch_score", "market_cap", "price"];

function ResultsTable({
  r,
  fields,
  sort,
  dir,
  onSort,
}: {
  r: { rows: ScreenRow[]; columns: string[] };
  fields: Map<string, ScreenField>;
  sort: string;
  dir: "asc" | "desc";
  onSort: (key: string) => void;
}) {
  const prefetch = usePrefetchStock();
  const metricCols = r.columns.filter((c) => !BASE_COLUMNS.includes(c));
  const cols = ["ticker", "category", ...BASE_COLUMNS, "day_change_pct", ...metricCols];
  const label = (c: string) =>
    c === "ticker"
      ? "Company"
      : c === "category"
        ? "Category"
        : c === "day_change_pct"
          ? "Day"
          : c === "lynch_score"
            ? "Lynch"
            : c === "market_cap"
              ? "Mkt cap"
              : (fields.get(c)?.label ?? c);
  const sortable = (c: string) => c === "ticker" || fields.has(c);
  const template = `minmax(220px, 1.6fr) 110px ${cols
    .slice(2)
    .map(() => "minmax(72px, 1fr)")
    .join(" ")}`;

  if (r.rows.length === 0) return <div className="empty-row">No company matches this screen</div>;
  return (
    <div className="table-scroll">
      <div className="screen-table" style={{ minWidth: 220 + 110 + (cols.length - 2) * 84 }}>
        <div className="s-grid h-head" style={{ gridTemplateColumns: template }}>
          {cols.map((c) => (
            <button
              key={c}
              type="button"
              disabled={!sortable(c)}
              className={`h-th ${c === "ticker" || c === "category" ? "" : "right"} ${sort === c ? "sorted" : ""}`}
              onClick={() => onSort(c)}
            >
              {label(c)}
              {sort === c ? (dir === "desc" ? " ▼" : " ▲") : ""}
            </button>
          ))}
        </div>
        {r.rows.map((row) => (
          <a
            key={row.ticker}
            href={stockPath(row.ticker)}
            className="s-grid h-row"
            style={{ gridTemplateColumns: template }}
            onMouseEnter={() => prefetch(row.ticker)}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey) return;
              e.preventDefault();
              navigate(stockPath(row.ticker));
            }}
          >
            <div className="ellipsis">
              <span className="h-ticker">{row.ticker}</span>
              <span className="h-name">{row.name}</span>
            </div>
            <div className="h-cat ellipsis">{row.category ?? DASH}</div>
            {cols.slice(2).map((c) => {
              const v = row[c] as number | null;
              if (c === "day_change_pct") {
                return (
                  <div key={c} className={`right num ${tone(v)}`}>
                    {signedPctPoints(v)}
                  </div>
                );
              }
              const kind = fields.get(c)?.kind;
              const growth = c.includes("growth");
              return (
                <div key={c} className={`right num ${c === "lynch_score" ? "strong" : ""} ${growth ? tone(v) : ""}`}>
                  {growth ? signedPct(v, 1) : fmt(v, kind)}
                </div>
              );
            })}
          </a>
        ))}
      </div>
    </div>
  );
}
