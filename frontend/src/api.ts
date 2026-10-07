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
  lynch: Lynch | null;
  sector_medians: Record<string, { value: number | null; companies: number }> | null;
  ranges_5y: Ranges;
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

export type LynchTest = {
  key: string;
  label: string;
  value: string | null;
  status: "pass" | "watch" | "fail" | "missing";
  weight: number;
  points: number;
  rule: string;
};

export type Lynch = {
  category: string | null;
  score: number | null;
  tests: LynchTest[];
  passed: number;
  counted: number;
};

export type Ranges = {
  years: number[];
  metrics: Record<string, { low: number | null; high: number | null; values: (number | null)[] }>;
  missing_prices: boolean;
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

export type TxType = "buy" | "sell" | "deposit" | "withdrawal" | "dividend";

export type Transaction = {
  id: number;
  date: string;
  type: TxType;
  ticker: string | null;
  shares: number | null;
  price: number | null;
  amount: number;
  note: string | null;
};

export type TradeInput = Omit<Transaction, "id" | "amount"> & { amount: number | null };

export type Holding = {
  ticker: string;
  name: string;
  is_company: boolean;
  is_fund: boolean;
  sector: string | null;
  shares: number;
  avg_cost: number | null;
  cost: number;
  price: number;
  day_change: number | null;
  day_change_pct: number | null;
  value: number;
  gain: number;
  gain_pct: number | null;
  weight: number | null;
  category: string | null;
  lynch_score: number | null;
  eps_ttm: number | null;
  eps_growth: number | null;
  pe: number | null;
  peg: number | null;
};

export type AllocRow = { name: string; value: number; weight: number };

export type Portfolio = {
  summary: {
    value: number;
    invested: number;
    cash: number;
    cost_basis: number;
    gain: number;
    gain_pct: number | null;
    realized: number;
    dividends: number;
    net_deposits: number;
    day_change: number;
    day_change_pct: number | null;
    return_1y: number | null;
    benchmark_1y: number | null;
    return_since: string | null;
    positions: number;
    trades: number;
  };
  holdings: Holding[];
  allocation: { by_category: AllocRow[]; kinds: AllocRow[]; by_sector: AllocRow[] };
  lookthrough: {
    pe: number | null;
    eps_growth: number | null;
    peg: number | null;
    lynch_score: number | null;
    largest_weight: number;
    largest: string;
    below_cost: number;
    stocks: number;
  } | null;
  activity: Transaction[];
  filings: (Filing & { ticker: string | null })[];
  market_open: boolean;
};

export type PerfRange = "1M" | "6M" | "YTD" | "1Y" | "ALL";

export type Performance = {
  range: PerfRange;
  points: { time: string; portfolio: number; benchmark: number | null; value: number }[];
  portfolio_return: number | null;
  benchmark_return: number | null;
  benchmark?: string;
};

export type FieldKind = "score" | "money" | "price" | "ratio" | "pct" | "times";
export type ScreenField = { key: string; label: string; kind: FieldKind };
export type ScreenOp = "gt" | "lt" | "between";
export type ScreenQuery = {
  filters: [string, ScreenOp | "gte" | "lte", number | number[]][];
  sectors?: string[];
  categories?: string[];
  sort?: string;
  dir?: "asc" | "desc";
};
export type SavedScreen = { id: number; name: string; query: ScreenQuery; builtin: boolean };
export type ScreenRow = {
  ticker: string;
  name: string;
  sector: string | null;
  tier: string;
  category: string | null;
  day_change_pct: number | null;
} & Record<string, number | string | null>;
export type ScreenResult = { total: number; rows: ScreenRow[]; columns: string[] };

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
  portfolio: () => request<Portfolio>("/api/portfolio"),
  performance: (range: PerfRange) =>
    request<Performance>(`/api/portfolio/performance?range=${range}`),
  transactions: () => request<Transaction[]>("/api/transactions"),
  addTrade: (t: TradeInput) =>
    request<Transaction>("/api/transactions", { method: "POST", body: JSON.stringify(t) }),
  editTrade: (id: number, t: TradeInput) =>
    request<Transaction>(`/api/transactions/${id}`, { method: "PUT", body: JSON.stringify(t) }),
  deleteTrade: (id: number) =>
    request<{ deleted: number }>(`/api/transactions/${id}`, { method: "DELETE" }),
  quote: (ticker: string) =>
    request<{ ticker: string; name: string | null; quote: Quote | null }>(
      `/api/quote/${encodeURIComponent(ticker)}`,
    ),
  screenerFields: () =>
    request<{ fields: ScreenField[]; sectors: string[]; categories: string[] }>("/api/screener/fields"),
  screener: (params: string) => request<ScreenResult>(`/api/screener?${params}`),
  screens: () => request<SavedScreen[]>("/api/screens"),
  saveScreen: (name: string, query: ScreenQuery) =>
    request<SavedScreen>("/api/screens", { method: "POST", body: JSON.stringify({ name, query }) }),
  deleteScreen: (id: number) => request<{ deleted: number }>(`/api/screens/${id}`, { method: "DELETE" }),
  unwatch: (ticker: string) =>
    request<Watchlist>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
};

export const keys = {
  stock: (t: string) => ["stock", t] as const,
  prices: (t: string, r: ChartRange) => ["prices", t, r] as const,
  watchlist: ["watchlist"] as const,
  status: ["status"] as const,
  portfolio: ["portfolio"] as const,
  performance: (r: PerfRange) => ["performance", r] as const,
  transactions: ["transactions"] as const,
};
