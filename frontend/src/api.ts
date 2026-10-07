export type Status = {
  version: string;
  now: string;
  database: { ok: boolean };
  keys: Record<string, boolean>;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  status: () => getJson<Status>("/api/status"),
};
