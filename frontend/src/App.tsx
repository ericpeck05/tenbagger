import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { Panel } from "./components/Panel";
import { TopBar } from "./components/TopBar";

export function App() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });

  return (
    <div className="app">
      <TopBar backendOk={status.isSuccess && status.data.database.ok} />
      <main className="placeholder">
        <Panel number={1} title="Scaffold">
          <p className="placeholder-lead">Phase 0 placeholder. The stock page arrives in phase 2.</p>
          <dl className="kv">
            <dt>Backend</dt>
            <dd className={status.isSuccess ? "up" : "down"}>
              {status.isSuccess ? "Connected" : status.isError ? "Not reachable" : "Checking"}
            </dd>
            <dt>Version</dt>
            <dd>{status.data?.version ?? "-"}</dd>
            {status.data &&
              Object.entries(status.data.keys).map(([name, present]) => (
                <KeyRow key={name} name={name} present={present} />
              ))}
          </dl>
        </Panel>
      </main>
    </div>
  );
}

function KeyRow({ name, present }: { name: string; present: boolean }) {
  return (
    <>
      <dt>{name.replaceAll("_", " ")}</dt>
      <dd style={{ color: present ? "var(--up)" : "var(--muted)" }}>{present ? "Set" : "Not set"}</dd>
    </>
  );
}
