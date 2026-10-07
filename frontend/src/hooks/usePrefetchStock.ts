import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api, keys } from "../api";

/** Hovering a row prefetches that stock, so the click feels instant. */
export function usePrefetchStock() {
  const qc = useQueryClient();
  return useCallback(
    (ticker: string) =>
      qc.prefetchQuery({
        queryKey: keys.stock(ticker),
        queryFn: () => api.stock(ticker),
        staleTime: 30_000,
      }),
    [qc],
  );
}
