import { useQuery } from "@tanstack/react-query";

import { api, keys } from "../api";

/** True when the backend runs on the made-up demo data (`make demo`). */
export function useDemo(): boolean {
  const status = useQuery({ queryKey: keys.status, queryFn: api.status, refetchInterval: 30_000 });
  return status.data?.demo ?? false;
}
