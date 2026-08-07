"use client";

import { useQuery } from "@tanstack/react-query";
import { getRegimeAnalytics, type RegimeAnalytics } from "@/shared/api/client";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";

const POLL_MS = 3000;

/** Per-bot win-rate/profit-factor/expectancy split by market regime
 * (volatility, trend, session) at entry (OBSERVABILITY_PLAN.md Phase 6) —
 * the regime-split counterpart to `useAnalytics.ts`'s overall bot/symbol
 * stats. Same 3000ms poll cadence as `useAnalytics.ts` since it reads the
 * same underlying trade table and is rendered right alongside the bot
 * performance table, so both should refresh in lockstep.
 *
 * `openFrom`/`openTo` are epoch seconds and come from the page's own date
 * filters, so this always covers the same window as the tables above it. */
export function useRegimeAnalytics(openFrom?: number, openTo?: number) {
  const accountId = useActiveAccount();

  const query = useQuery({
    queryKey: queryKeys.analytics.regimes(accountId, openFrom, openTo),
    queryFn: ({ signal }) =>
      getRegimeAnalytics(accountId as string, { open_from: openFrom, open_to: openTo }, signal),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  const regimes: RegimeAnalytics[] = query.data ?? [];
  return {
    regimes,
    loading: query.isFetching,
    error: query.isError ? "Failed to load regime analytics." : null,
  };
}

export type UseRegimeAnalytics = ReturnType<typeof useRegimeAnalytics>;
