import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type TradeInput, type Transaction, type TxType } from "../api";
import { num } from "../format";

const TYPES: { type: TxType; label: string }[] = [
  { type: "buy", label: "Buy" },
  { type: "sell", label: "Sell" },
  { type: "deposit", label: "Deposit" },
  { type: "withdrawal", label: "Withdraw" },
  { type: "dividend", label: "Dividend" },
];

function today(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

type Props = { editing: Transaction | null; onClose: () => void };

/** Add or edit one entry in the trade log. Opens with T on the portfolio page. */
export function TradeForm({ editing, onClose }: Props) {
  const qc = useQueryClient();
  const [type, setType] = useState<TxType>(editing?.type ?? "buy");
  const [date, setDate] = useState(editing?.date ?? today());
  const [ticker, setTicker] = useState(editing?.ticker ?? "");
  const [shares, setShares] = useState(editing?.shares != null ? String(editing.shares) : "");
  const [price, setPrice] = useState(editing?.price != null ? String(editing.price) : "");
  const [amount, setAmount] = useState(
    editing && !["buy", "sell"].includes(editing.type) ? String(editing.amount) : "",
  );
  const [note, setNote] = useState(editing?.note ?? "");
  const [hint, setHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const isTrade = type === "buy" || type === "sell";

  useEffect(() => first.current?.focus(), [type]);

  // Prefill the price from the latest quote when a ticker is entered.
  const lookup = async () => {
    const t = ticker.trim();
    if (!t || !isTrade) return;
    try {
      const q = await api.quote(t);
      setHint(q.name ? `${q.ticker}, ${q.name}` : q.ticker);
      if (!price && q.quote) setPrice(String(q.quote.price));
    } catch {
      setHint(`No quote found for ${t.toUpperCase()}`);
    }
  };

  const done = () => {
    qc.invalidateQueries({ queryKey: ["portfolio"] });
    qc.invalidateQueries({ queryKey: ["performance"] });
    qc.invalidateQueries({ queryKey: ["transactions"] });
    onClose();
  };

  const save = useMutation({
    mutationFn: (input: TradeInput) =>
      editing ? api.editTrade(editing.id, input) : api.addTrade(input),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteTrade(editing!.id),
    onSuccess: done,
    onError: (e: Error) => setError(e.message),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const n = (s: string) => (s.trim() === "" ? null : Number(s.replace(/,/g, "")));
    save.mutate({
      date,
      type,
      ticker: isTrade || (type === "dividend" && ticker.trim()) ? ticker.trim() : null,
      shares: isTrade ? n(shares) : null,
      price: isTrade ? n(price) : null,
      amount: isTrade ? null : n(amount),
      note: note.trim() || null,
    });
  };

  const total = isTrade && shares && price ? Number(shares) * Number(price) : null;

  return (
    <div className="overlay" data-modal-open onMouseDown={onClose}>
      <form
        className="trade-form"
        role="dialog"
        aria-label={editing ? "Edit trade" : "Add trade"}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
        onSubmit={submit}
      >
        <div className="panel-bar">
          <div className="panel-bar-left">
            <h2 className="panel-title">{editing ? "Edit trade" : "Add trade"}</h2>
          </div>
          <span className="key">ESC</span>
        </div>
        <div className="trade-body">
          <div role="group" aria-label="Type" className="seg seg-full">
            {TYPES.map((t) => (
              <button
                key={t.type}
                type="button"
                aria-pressed={type === t.type}
                className={type === t.type ? "seg-btn on" : "seg-btn"}
                onClick={() => setType(t.type)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="fields">
            <label className="field">
              <span>Date</span>
              <input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required />
            </label>
            {(isTrade || type === "dividend") && (
              <label className="field">
                <span>Ticker{type === "dividend" ? ", optional" : ""}</span>
                <input
                  ref={first}
                  value={ticker}
                  onChange={(e) => {
                    setTicker(e.target.value.toUpperCase());
                    setHint(null);
                  }}
                  onBlur={lookup}
                  placeholder="AAPL"
                  autoComplete="off"
                  spellCheck={false}
                  required={isTrade}
                />
              </label>
            )}
            {isTrade ? (
              <>
                <label className="field">
                  <span>Shares</span>
                  <input inputMode="decimal" value={shares} onChange={(e) => setShares(e.target.value)} required />
                </label>
                <label className="field">
                  <span>Price per share</span>
                  <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} required />
                </label>
              </>
            ) : (
              <label className="field">
                <span>Amount</span>
                <input
                  ref={type === "dividend" ? undefined : first}
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                />
              </label>
            )}
            <label className="field field-wide">
              <span>Note, optional</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
            </label>
          </div>
          <div className="trade-meta">
            <span>{hint}</span>
            {total != null && Number.isFinite(total) && <span className="num">Total {num(total)}</span>}
          </div>
          {error && (
            <div className="form-error" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="trade-actions">
          {editing && (
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => (confirmDelete ? remove.mutate() : setConfirmDelete(true))}
              disabled={remove.isPending}
            >
              {confirmDelete ? "Confirm delete" : "Delete"}
            </button>
          )}
          <span className="trade-private">Stored on this computer only</span>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {editing ? "Save" : "Add trade"}
          </button>
        </div>
      </form>
    </div>
  );
}
