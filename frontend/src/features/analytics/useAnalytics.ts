"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getBotAnalytics,
  getSymbolAnalytics,
  type AnalyticsDateFilters,
  type BotAnalytics,
  type SymbolAnalytics,
} from "@/shared/api/client";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";

const POLL_MS = 3000;

/** Loads both analytics breakdowns together — the page renders symbol
 * stats, bot stats, and the equity-curve chart from the same fetch, so one
 * hook keeps their loading/error/refresh state in sync instead of three
 * components racing independent requests.
 *
 * Backed by TanStack Query with a 3000ms refetch interval (same cadence as
 * `features/history/useTradeHistory.ts` and `features/trading/useAllPositions.ts`)
 * so a trade closing — bot-driven SL/TP or manual — shows up in win
 * rate/profit factor/equity curve without a manual reload or clicking
 * "Refresh". `refresh()` is still exposed for an immediate on-demand
 * invalidation (wired to the header's Refresh button). */
export function useAnalytics(filters?: AnalyticsDateFilters) {
  const accountId = useActiveAccount();
  const queryClient = useQueryClient();
  const openFrom = filters?.open_from;
  const openTo = filters?.open_to;

  const symbolsQuery = useQuery({
    queryKey: queryKeys.analytics.symbols(accountId, openFrom, openTo),
    queryFn: () => getSymbolAnalytics(accountId as string, filters),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  const botsQuery = useQuery({
    queryKey: queryKeys.analytics.bots(accountId, openFrom, openTo),
    queryFn: () => getBotAnalytics(accountId as string, filters),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  const symbols: SymbolAnalytics[] = symbolsQuery.data ?? [];
  const bots: BotAnalytics[] = botsQuery.data ?? [];
  const loading = symbolsQuery.isFetching || botsQuery.isFetching;
  const error = symbolsQuery.isError || botsQuery.isError ? "Failed to load analytics." : null;

  const refresh = useCallback(() => {
    if (!accountId) return;
    queryClient.invalidateQueries({ queryKey: queryKeys.analytics.symbols(accountId, openFrom, openTo) });
    queryClient.invalidateQueries({ queryKey: queryKeys.analytics.bots(accountId, openFrom, openTo) });
  }, [accountId, openFrom, openTo, queryClient]);

  return { symbols, bots, loading, error, refresh };
}
