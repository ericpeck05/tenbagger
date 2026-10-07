import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, keys, type SearchHit } from "../api";
import { num, shortDate, signedPctPoints, tone } from "../format";
import { navigate, stockPath } from "../router";
import { usePrefetchStock } from "../hooks/usePrefetchStock";

type Props = { onClose: () => void };

/** The command line: ticker or company search over the local database.
 *  Up and Down move, Enter opens, Tab adds to the watchlist, Esc closes. */
export function SearchOverlay({ onClose }: Props) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [flash, setFlash] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const prefetch = usePrefetchStock();

  const res = useQuery({
    queryKey: ["search", q.trim().toUpperCase()],
    queryFn: () => api.search(q),
    enabled: q.trim().length > 0,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });

  const hits: SearchHit[] = useMemo(
    () => (q.trim() && res.data ? [...res.data.warm, ...res.data.other] : []),
    [q, res.data],
  );
  const warmCount = q.trim() && res.data ? res.data.warm.length : 0;
  const selected = hits[Math.min(sel, hits.length - 1)];

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    if (!selected) return;
    prefetch(selected.ticker);
    document.querySelector(".hit.on")?.scrollIntoView({ block: "nearest" });
  }, [selected, prefetch]);

  const go = (hit: SearchHit | undefined) => {
    if (!hit) return;
    onClose();
    navigate(stockPath(hit.ticker));
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(selected);
    } else if (e.key === "Tab" && selected) {
      e.preventDefault();
      api.watch(selected.ticker).then((wl) => {
        qc.setQueryData(keys.watchlist, wl);
        qc.invalidateQueries({ queryKey: keys.stock(selected.ticker) });
        setFlash(`${selected.ticker} added to watchlist`);
      });
    }
  };

  const row = (hit: SearchHit, i: number) => {
    const on = i === sel;
    const warm = i < warmCount;
    return (
      <a
        key={hit.ticker}
        href={stockPath(hit.ticker)}
        className={on ? "hit on" : "hit"}
        onMouseEnter={() => setSel(i)}
        onClick={(e) => {
          e.preventDefault();
          go(hit);
        }}
      >
        <span className="hit-ticker">{hit.ticker}</span>
        <span className="hit-name">
          {hit.name}
          {hit.sector && <span className="hit-sector">, {hit.sector}</span>}
        </span>
        {warm ? (
          <>
            <span className="num">{hit.price != null ? num(hit.price) : ""}</span>
            <span className={`hit-change num ${on ? "" : tone(hit.change_pct)}`}>
              {hit.change_pct != null ? signedPctPoints(hit.change_pct) : ""}
            </span>
          </>
        ) : (
          <span className="hit-note">
            {hit.cached_at ? `Cached ${shortDate(hit.cached_at)}` : "New, about 1 sec"}
          </span>
        )}
        <span className="hit-enter">{on ? <span className="key key-on">ENTER</span> : null}</span>
      </a>
    );
  };

  return (
    <div className="overlay" data-modal-open onMouseDown={onClose}>
      <div
        className="search"
        role="dialog"
        aria-label="Search any ticker or company"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="search-input">
          <span aria-hidden="true" className="prompt">
            &gt;
          </span>
          <label htmlFor="q" className="sr-only">
            Search any ticker or company
          </label>
          <input
            id="q"
            ref={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setSel(0);
            }}
            onKeyDown={onKey}
            autoComplete="off"
            spellCheck={false}
            placeholder="Ticker or company"
          />
          <span className="key">ESC</span>
        </div>
        <div className="search-results">
          {q.trim() === "" && <div className="search-hint">Type a ticker like NVDA, or a name like Coca-Cola</div>}
          {q.trim() !== "" && res.data && hits.length === 0 && (
            <div className="search-hint">No company matches {q.trim()}</div>
          )}
          {warmCount > 0 && (
            <div className="group-head">
              <span className="group-name">On hand</span>
              <span>Opens instantly</span>
            </div>
          )}
          {hits.slice(0, warmCount).map((h, i) => row(h, i))}
          {hits.length > warmCount && (
            <div className="group-head">
              <span className="group-name">Everything else</span>
              <span>Fundamentals ready, price on open</span>
            </div>
          )}
          {hits.slice(warmCount).map((h, i) => row(h, i + warmCount))}
        </div>
        <div className="search-foot">
          <span>
            <span className="key key-on">UP / DN</span> Move
          </span>
          <span>
            <span className="key key-on">ENTER</span> Open
          </span>
          <span>
            <span className="key key-on">TAB</span> Watch
          </span>
          <span className="search-flash">{flash}</span>
        </div>
      </div>
    </div>
  );
}
