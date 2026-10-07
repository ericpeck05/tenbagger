import { useSyncExternalStore } from "react";

/** A tiny router over the History API: /stock/AAPL, /portfolio, /screener. */

export type Route =
  | { page: "stock"; ticker: string | null }
  | { page: "portfolio" }
  | { page: "screener" };

function parse(path: string): Route {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "portfolio") return { page: "portfolio" };
  if (parts[0] === "screener") return { page: "screener" };
  if (parts[0] === "stock" && parts[1]) {
    return { page: "stock", ticker: decodeURIComponent(parts[1]).toUpperCase() };
  }
  return { page: "stock", ticker: null };
}

const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("popstate", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("popstate", cb);
  };
}

export function navigate(path: string, { replace = false } = {}) {
  if (path === window.location.pathname) return;
  if (replace) window.history.replaceState(null, "", path);
  else window.history.pushState(null, "", path);
  listeners.forEach((cb) => cb());
  window.scrollTo({ top: 0 });
}

export const stockPath = (ticker: string) => `/stock/${encodeURIComponent(ticker)}`;

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname);
  return parse(path);
}
