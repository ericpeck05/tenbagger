import { useIsFetching } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { SearchOverlay } from "./components/SearchOverlay";
import { TopBar } from "./components/TopBar";
import { useHotkeys } from "./hooks/useHotkeys";
import { StockPage } from "./pages/StockPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ScreenerPage } from "./pages/ScreenerPage";
import { jumpTo, type PanelLink, PANELS, PORTFOLIO_PANELS, SCREENER_PANELS } from "./panels";
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
      {route.page === "stock" && <JumpBar panels={PANELS} hint="Press a number to jump, W to watch" />}
      {route.page === "portfolio" && (
        <JumpBar panels={PORTFOLIO_PANELS} hint="Press a number to jump, T to add a trade" />
      )}
      {route.page === "stock" && route.ticker && <StockPage ticker={route.ticker} />}
      {route.page === "portfolio" && <PortfolioPage />}
      {route.page === "screener" && (
        <>
          <JumpBar panels={SCREENER_PANELS} hint="Press a number to jump, / to search" />
          <ScreenerPage />
        </>
      )}
      {searching && <SearchOverlay onClose={() => setSearching(false)} />}
    </div>
  );
}

function JumpBar({ panels, hint }: { panels: readonly PanelLink[]; hint: string }) {
  return (
    <nav aria-label="Jump to panel" className="jumpbar">
      {panels.map((p) => (
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
      <span className="jump-hint">{hint}</span>
    </nav>
  );
}
