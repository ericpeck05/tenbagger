export type Quote = {
  price: number;
  change: number | null;
  change_pct: number | null;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  quote_time: string | null;
  fetched_at: string;
};

export type Ratios = Record<string, number | null>;

export type Filing = { form: string; title: string; filed_at: string; url: string };

export type Stock = {
  ticker: string;
  tickers: string[];
  cik: number;
  name: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  tier: string;
  supported: boolean;
  watching: boolean;
  quote: Quote | null;
  quote_refreshing: boolean;
  ratios: Ratios | null;
  range_52w: { low: number; high: number } | null;
  annual: { years: number[]; revenue: (number | null)[]; eps: (number | null)[] };
  filings: Filing[];
  lynch: null;
  sector_medians: null;
  ranges_5y: null;
  market_open: boolean;
  sources: {
    fundamentals: {
      provider: string;
      through: string | null;
      form: string | null;
      period_end: string | null;
    };
    quote: { provider: string; fetched_at: string | null };
    prices: { provider: string; last_date: string | null };
  };
};

export type Bar = { time: string; open: number; high: number; low: number; close: number };

export type ChartRange = "1M" | "6M" | "YTD" | "1Y" | "5Y" | "MAX";

export type Prices = {
  ticker: string;
  range: ChartRange;
  interval: "1d" | "1w";
  bars: Bar[];
  change_pct: number | null;
  range_52w: { low: number; high: number } | null;
  last_date: string | null;
  today?: string;
};

export type SearchHit = {
  ticker: string;
  name: string;
  sector: string | null;
  price?: number | null;
  change_pct?: number | null;
  cached_at?: string | null;
};

export type SearchResult = { query: string; warm: SearchHit[]; other: SearchHit[] };

export type Watchlist = {
  watch: { ticker: string; name: string; quote: Quote | null }[];
  recent: { ticker: string; name: string; cached_at: string | null }[];
};

export type Status = {
  version: string;
  now: string;
  database: { ok: boolean; companies: number; quotes: number; price_bars: number };
  keys: Record<string, boolean>;
  market: { open: boolean };
  jobs: { newest_quote_at: string | null; oldest_quote_at: string | null };
  tiers: Record<string, number>;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  status: () => request<Status>("/api/status"),
  stock: (ticker: string) => request<Stock>(`/api/stock/${encodeURIComponent(ticker)}`),
  prices: (ticker: string, range: ChartRange) =>
    request<Prices>(`/api/stock/${encodeURIComponent(ticker)}/prices?range=${range}`),
  search: (q: string) => request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),
  watchlist: () => request<Watchlist>("/api/watchlist"),
  watch: (ticker: string) =>
    request<Watchlist>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
  unwatch: (ticker: string) =>
    request<Watchlist>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
};

export const keys = {
  stock: (t: string) => ["stock", t] as const,
  prices: (t: string, r: ChartRange) => ["prices", t, r] as const,
  watchlist: ["watchlist"] as const,
  status: ["status"] as const,
};
