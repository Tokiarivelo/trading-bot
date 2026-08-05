"use client";

import { useQuery } from "@tanstack/react-query";
import { getSignalFunnel, type BotFunnel } from "@/shared/api/client";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";

const POLL_MS = 15000;

/** The per-bot veto funnel for the selected period — "of N signals this bot
 * fired, why did only M trade?" (OBSERVABILITY_PLAN.md Phase 2).
 *
 * Polled far more slowly than the trade analytics beside it (15s vs 3s):
 * signals only change on a candle close, and the endpoint aggregates the
 * whole period's decision rows rather than a page of trades.
 *
 * `from`/`to` are epoch seconds and come from the page's own date filters, so
 * the funnel always covers the same window as the tables above it. Omitted,
 * the backend defaults to the last 14 days.
 */
export function useSignalFunnel(from?: number, to?: number) {
  const accountId = useActiveAccount();

  const query = useQuery({
    queryKey: queryKeys.analytics.signalFunnel(accountId, from, to),
    queryFn: () => getSignalFunnel(accountId as string, { from, to }),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  const funnels: BotFunnel[] = query.data ?? [];
  return {
    funnels,
    loading: query.isPending,
    error: query.isError ? "Failed to load the signal funnel." : null,
  };
}

export type UseSignalFunnel = ReturnType<typeof useSignalFunnel>;
