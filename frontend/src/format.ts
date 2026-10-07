/** Number and date formatting. Missing values are always a dash, never zero. */

export const DASH = "—";

type N = number | null | undefined;

const has = (n: N): n is number => n !== null && n !== undefined && Number.isFinite(n);

export function num(n: N, digits = 2): string {
  if (!has(n)) return DASH;
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Signed number for gains and losses: +0.62, -1.75. */
export function signed(n: N, digits = 2): string {
  if (!has(n)) return DASH;
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}${num(Math.abs(n), digits)}`;
}

/** A fraction as a percent: 0.146 -> "14.6%". */
export function pct(n: N, digits = 1): string {
  return has(n) ? `${num(n * 100, digits)}%` : DASH;
}

/** A fraction as a signed percent: 0.18 -> "+18.0%". */
export function signedPct(n: N, digits = 1): string {
  return has(n) ? `${signed(n * 100, digits)}%` : DASH;
}

/** A value already in percent units (Finnhub's day change) as a signed percent. */
export function signedPctPoints(n: N, digits = 2): string {
  return has(n) ? `${signed(n, digits)}%` : DASH;
}

/** Large amounts: 6.03B, 125.0M, 2.71T. */
export function big(n: N, digits = 2): string {
  if (!has(n)) return DASH;
  const a = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (a >= 1e12) return `${sign}${num(a / 1e12, digits)}T`;
  if (a >= 1e9) return `${sign}${num(a / 1e9, digits)}B`;
  if (a >= 1e6) return `${sign}${num(a / 1e6, 1)}M`;
  if (a >= 1e3) return `${sign}${num(a / 1e3, 1)}K`;
  return `${sign}${num(a, 0)}`;
}

export function times(n: N, digits = 1): string {
  return has(n) ? `${num(n, digits)}x` : DASH;
}

/** CSS class for a gain or loss. */
export function tone(n: N): string {
  if (!has(n) || n === 0) return "";
  return n > 0 ? "up" : "down";
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return DASH;
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Oct 2" from an ISO date or timestamp. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

/** "Oct 2, 2026" */
export function longDate(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
