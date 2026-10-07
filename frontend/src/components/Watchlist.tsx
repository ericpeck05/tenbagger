import { useQuery } from "@tanstack/react-query";

import { api, keys } from "../api";
import { DASH, num, shortDate, signedPctPoints, tone } from "../format";
import { usePrefetchStock } from "../hooks/usePrefetchStock";
import { navigate, stockPath } from "../router";

function open(e: React.MouseEvent, ticker: string) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; // let the browser open a tab
  e.preventDefault();
  navigate(stockPath(ticker));
}

export function WatchlistColumn({ current }: { current: string }) {
  const wl = useQuery({ queryKey: keys.watchlist, queryFn: api.watchlist, refetchInterval: 30_000 });
  const prefetch = usePrefetchStock();
  const watch = wl.data?.watch ?? [];
  const recent = wl.data?.recent ?? [];

  return (
    <nav aria-label="Watchlist" className="side">
      <div className="panel">
        <div className="panel-bar side-bar">
          <h2 className="side-title">Watchlist</h2>
          <span className="side-note">On hand</span>
        </div>
        {watch.length === 0 && (
          <div className="empty-row">
            Press <span className="key">W</span> on a stock to watch it
          </div>
        )}
        {watch.map((w) => {
          const on = w.ticker === current;
          return (
            <a
              key={w.ticker}
              href={stockPath(w.ticker)}
              className={on ? "side-row on" : "side-row"}
              aria-current={on ? "page" : undefined}
              onMouseEnter={() => prefetch(w.ticker)}
              onClick={(e) => open(e, w.ticker)}
            >
              <span className="side-name">
                <span className="side-ticker">{w.ticker}</span>
                <span className="side-company">{w.name}</span>
              </span>
              <span className="side-quote num">
                <span>{w.quote ? num(w.quote.price) : DASH}</span>
                <span className={`side-change ${tone(w.quote?.change_pct)}`}>
                  {signedPctPoints(w.quote?.change_pct)}
                </span>
              </span>
            </a>
          );
        })}
      </div>
      <div className="panel">
        <div className="panel-bar side-bar">
          <h2 className="side-title">Recent</h2>
          <span className="side-note">On request</span>
        </div>
        {recent.length === 0 && <div className="empty-row">Stocks outside the S&amp;P 500 you open show here</div>}
        {recent.map((r) => (
          <a
            key={r.ticker}
            href={stockPath(r.ticker)}
            className={r.ticker === current ? "side-row on" : "side-row"}
            onMouseEnter={() => prefetch(r.ticker)}
            onClick={(e) => open(e, r.ticker)}
          >
            <span className="side-name">
              <span className="side-ticker">{r.ticker}</span>
              <span className="side-company">{r.name}</span>
            </span>
            <span className="side-note">{r.cached_at ? `Cached ${shortDate(r.cached_at)}` : "New"}</span>
          </a>
        ))}
      </div>
    </nav>
  );
}
