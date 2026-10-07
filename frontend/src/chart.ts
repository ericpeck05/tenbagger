import type { Bar, Prices, Quote } from "./api";

/** The live quote as today's bar, if it is newer than the last stored bar. */
export function withLiveBar(prices: Prices, quote: Quote | null): Bar[] {
  const bars = prices.bars;
  if (!quote || !quote.quote_time || bars.length === 0 || !prices.today) return bars;
  const quoteDay = new Date(quote.quote_time).toLocaleDateString("en-CA", {
    timeZone: "America/New_York",
  });
  const last = bars[bars.length - 1]!;
  if (quoteDay <= (prices.last_date ?? last.time) || quote.open == null) return bars;
  const today: Bar = {
    time: quoteDay,
    open: quote.open,
    high: Math.max(quote.high ?? quote.price, quote.price),
    low: Math.min(quote.low ?? quote.price, quote.price),
    close: quote.price,
  };
  if (prices.interval === "1w" && sameWeek(last.time, quoteDay)) {
    const merged = {
      ...last,
      high: Math.max(last.high, today.high),
      low: Math.min(last.low, today.low),
      close: today.close,
    };
    return [...bars.slice(0, -1), merged];
  }
  return [...bars, today];
}

function sameWeek(a: string, b: string): boolean {
  const monday = (iso: string) => {
    const d = new Date(`${iso}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  };
  return monday(a) === monday(b);
}

export function lastBar(prices: Prices | undefined, quote: Quote | null): Bar | null {
  if (!prices) return null;
  const bars = withLiveBar(prices, quote);
  return bars[bars.length - 1] ?? null;
}
