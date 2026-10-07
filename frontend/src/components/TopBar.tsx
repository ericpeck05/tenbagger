const TABS = ["Stock", "Portfolio", "Screener"] as const;

export function TopBar({ backendOk }: { backendOk: boolean }) {
  return (
    <header className="topbar">
      <div className="brand">Tenbagger</div>
      <button type="button" className="cmdline" disabled title="Search arrives in phase 2">
        <span className="cmdline-prompt">&gt;</span>
        <span aria-hidden="true" className="cmdline-cursor" />
        <span className="cmdline-hint">Ticker, company, or command</span>
        <span className="key">/</span>
      </button>
      <nav aria-label="Sections" className="tabs">
        {TABS.map((tab, i) => (
          <a key={tab} href="#" className={i === 0 ? "tab tab-active" : "tab"}>
            {tab}
          </a>
        ))}
      </nav>
      <div className="topbar-status">
        <span className="dot" style={{ background: backendOk ? "var(--up)" : "var(--down)" }} />
        <span>{backendOk ? "Backend connected" : "Backend offline"}</span>
      </div>
    </header>
  );
}
