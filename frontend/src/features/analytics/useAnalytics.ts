"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getBotAnalytics,
  getSymbolAnalytics,
  type BotAnalytics,
  type SymbolAnalytics,
} from "@/shared/api/client";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";

/** Loads both analytics breakdowns together — the page renders symbol
 * stats, bot stats, and the equity-curve chart from the same fetch, so one
 * hook keeps their loading/error/refresh state in sync instead of three
 * components racing independent requests.
 *
 * Backed by TanStack Query (one-shot, no `refetchInterval` — this data isn't
 * polled, just fetched once per account and re-fetched on demand via
 * `refresh()`), which also gets this hook caching/dedup for free per
 * `shared/api/queryKeys.ts`'s convention. */
export function useAnalytics() {
  const accountId = useActiveAccount();
  const queryClient = useQueryClient();

  const symbolsQuery = useQuery({
    queryKey: queryKeys.analytics.symbols(accountId),
    queryFn: () => getSymbolAnalytics(accountId as string),
    enabled: accountId !== null,
  });

  const botsQuery = useQuery({
    queryKey: queryKeys.analytics.bots(accountId),
    queryFn: () => getBotAnalytics(accountId as string),
    enabled: accountId !== null,
  });

  const symbols: SymbolAnalytics[] = symbolsQuery.data ?? [];
  const bots: BotAnalytics[] = botsQuery.data ?? [];
  const loading = symbolsQuery.isFetching || botsQuery.isFetching;
  const error = symbolsQuery.isError || botsQuery.isError ? "Failed to load analytics." : null;

  const refresh = useCallback(() => {
    if (!accountId) return;
    queryClient.invalidateQueries({ queryKey: queryKeys.analytics.symbols(accountId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.analytics.bots(accountId) });
  }, [accountId, queryClient]);

  return { symbols, bots, loading, error, refresh };
}
