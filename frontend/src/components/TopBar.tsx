import { useQuery } from "@tanstack/react-query";

import { api, keys } from "../api";
import { ago } from "../format";
import { navigate, type Route, stockPath } from "../router";

const TABS = [
  { page: "stock", label: "Stock" },
  { page: "portfolio", label: "Portfolio" },
  { page: "screener", label: "Screener" },
] as const;

type Props = { route: Route; ticker: string | null; onSearch: () => void; busy: boolean };

export function TopBar({ route, ticker, onSearch, busy }: Props) {
  const status = useQuery({ queryKey: keys.status, queryFn: api.status, refetchInterval: 30_000 });
  const st = status.data;

  let dot = "var(--down)";
  let text = "Backend offline";
  if (st) {
    if (st.demo) {
      dot = "var(--watch)";
      text = "Demo mode, prices are made up";
    } else if (!st.keys.finnhub) {
      dot = "var(--watch)";
      text = "No quotes: add a Finnhub key";
    } else if (st.market.open) {
      dot = "var(--up)";
      text = `Market open, quotes ${ago(st.jobs.oldest_quote_at).replace(" ago", " old")}`;
    } else {
      dot = "var(--muted)";
      text = "Market closed";
    }
  }

  return (
    <header className="topbar">
      {busy && <div className="busy-bar" aria-hidden="true" />}
      <div className="brand">Tenbagger</div>
      <button type="button" className="cmdline" onClick={onSearch} aria-label="Search, press slash">
        <span className="cmdline-prompt">&gt;</span>
        {ticker && route.page === "stock" && <span className="cmdline-ticker">{ticker}</span>}
        <span aria-hidden="true" className="cmdline-cursor" />
        <span className="cmdline-hint">Ticker, company, or command</span>
        <span className="key">/</span>
      </button>
      <nav aria-label="Sections" className="tabs">
        {TABS.map((tab) => {
          const on = route.page === tab.page;
          const href = tab.page === "stock" ? stockPath(ticker ?? "AAPL") : `/${tab.page}`;
          return (
            <a
              key={tab.page}
              href={href}
              className={on ? "tab tab-active" : "tab"}
              aria-current={on ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(href);
              }}
            >
              {tab.label}
            </a>
          );
        })}
      </nav>
      <div className="topbar-status">
        <span className="dot" style={{ background: dot }} />
        <span>{text}</span>
      </div>
    </header>
  );
}
