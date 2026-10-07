import { useIsFetching } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { SearchOverlay } from "./components/SearchOverlay";
import { TopBar } from "./components/TopBar";
import { useHotkeys } from "./hooks/useHotkeys";
import { StockPage } from "./pages/StockPage";
import { jumpTo, PANELS } from "./panels";
import { navigate, stockPath, useRoute } from "./router";

function lastTicker(): string {
  try {
    return localStorage.getItem("lastTicker") || "AAPL";
  } catch {
    return "AAPL";
  }
}

export function App() {
  const route = useRoute();
  const [searching, setSearching] = useState(false);
  const busy = useIsFetching({ queryKey: ["stock"] }) > 0;

  const ticker = route.page === "stock" ? route.ticker : null;
  useEffect(() => {
    if (route.page === "stock" && !route.ticker) {
      navigate(stockPath(lastTicker()), { replace: true });
    }
  }, [route]);

  useHotkeys(
    useCallback((e: KeyboardEvent) => {
      if (e.key === "/") {
        setSearching(true);
        return true;
      }
      return false;
    }, []),
  );

  return (
    <div className="app">
      <TopBar route={route} ticker={ticker} onSearch={() => setSearching(true)} busy={busy} />
      {route.page === "stock" && (
        <nav aria-label="Jump to panel" className="jumpbar">
          {PANELS.map((p) => (
            <a
              key={p.id}
              href={`#${p.id}`}
              onClick={(e) => {
                e.preventDefault();
                jumpTo(p.id);
              }}
            >
              <span className="jump-num">{p.n}</span>
              {p.label}
            </a>
          ))}
          <span className="jump-hint">Press a number to jump, W to watch</span>
        </nav>
      )}
      {route.page === "stock" && route.ticker && <StockPage ticker={route.ticker} />}
      {route.page === "portfolio" && (
        <ComingSoon title="Portfolio" phase={3} what="trade log, holdings, allocation, and performance" />
      )}
      {route.page === "screener" && (
        <ComingSoon title="Screener" phase={6} what="filters and sorting across every company" />
      )}
      {searching && <SearchOverlay onClose={() => setSearching(false)} />}
    </div>
  );
}

function ComingSoon({ title, phase, what }: { title: string; phase: number; what: string }) {
  return (
    <main className="soon">
      <section className="panel">
        <div className="panel-bar">
          <div className="panel-bar-left">
            <h2 className="panel-title">{title}</h2>
          </div>
        </div>
        <div className="panel-body">
          The {title.toLowerCase()} ({what}) arrives in phase {phase}.
        </div>
      </section>
    </main>
  );
}
