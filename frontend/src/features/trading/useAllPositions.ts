"use client";

/**
 * Account-wide (every symbol) open positions + pending orders, plus a
 * ticket -> skill lookup and a ticket -> full journaled-trade lookup, both
 * sourced from the journal's open trades. Backed by TanStack Query (see
 * `shared/api/queryKeys.ts` for the key convention) instead of a manual
 * `setInterval` poll — each of the three fetches is its own `useQuery` with
 * `refetchInterval: 3000`, so the header's total floating P/L and the
 * Active Orders / Positions panel (including its Strategy column and "why"
 * decision-context modal) share one cache entry per query key rather than
 * each polling `/broker/positions` separately, even across the multiple
 * components that call this hook (query-key dedup, not manual derivation).
 */

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useActiveAccount } from "@/shared/api/account-context";
import { queryKeys } from "@/shared/api/queryKeys";
import {
  getPendingOrders,
  getPositions,
  getTradeHistory,
  type TradeHistoryItem,
} from "@/shared/api/client";

const POLL_MS = 3000;

export function useAllPositions(options?: {
  /**
   * Whether the trade-history leg (the heaviest of the three fetches —
   * `getTradeHistory(accountId, { outcome: "open", limit: 500 })`) should
   * run at all. Defaults to `true` so callers that don't pass this (e.g.
   * `BotsBySymbolPanel`, which has no visibility toggle to gate against) keep
   * today's always-fetch behavior. `page.tsx` passes `OrdersDock`'s visible
   * state here, since `skillByTicket`/`openTradeByTicket` only feed
   * `AllOrdersPanel` inside that dock. Wired through `useQuery`'s `enabled`
   * rather than an early-return inside a manual fetch function.
   */
  needsTradeHistory?: boolean;
}) {
  const needsTradeHistory = options?.needsTradeHistory ?? true;
  const accountId = useActiveAccount();
  const queryClient = useQueryClient();

  const positionsQuery = useQuery({
    queryKey: queryKeys.trading.positions(accountId),
    queryFn: () => getPositions(accountId as string),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  const pendingOrdersQuery = useQuery({
    queryKey: queryKeys.trading.pendingOrders(accountId),
    queryFn: () => getPendingOrders(accountId as string),
    enabled: accountId !== null,
    refetchInterval: POLL_MS,
  });

  // outcome="open" scopes this to currently-open trades — 500 is the
  // endpoint's max page size, far above any realistic open-position count.
  const openTradesQuery = useQuery({
    queryKey: queryKeys.trading.openTrades(accountId),
    queryFn: () => getTradeHistory(accountId as string, { outcome: "open", limit: 500 }),
    enabled: accountId !== null && needsTradeHistory,
    refetchInterval: POLL_MS,
  });

  const positions = useMemo(() => positionsQuery.data ?? [], [positionsQuery.data]);
  const pendingOrders = useMemo(() => pendingOrdersQuery.data ?? [], [pendingOrdersQuery.data]);

  // Deliberately derived from whatever `openTradesQuery.data` last held
  // (React Query keeps prior data on a failed refetch, and leaves it
  // untouched while the query is disabled) rather than clearing to empty
  // when the dock is hidden: stale-for-up-to-3s data reads better than a
  // flash of "no data" once the dock is shown again.
  const openTradeItems: TradeHistoryItem[] = useMemo(
    () => openTradesQuery.data?.items ?? [],
    [openTradesQuery.data],
  );
  const skillByTicket = useMemo(
    () => new Map(openTradeItems.map((item) => [item.id, item.skill])),
    [openTradeItems],
  );
  const openTradeByTicket = useMemo(
    () => new Map(openTradeItems.map((item) => [item.id, item])),
    [openTradeItems],
  );

  const refresh = useCallback(() => {
    if (!accountId) return; // account list not resolved yet (initial load)
    queryClient.invalidateQueries({ queryKey: queryKeys.trading.positions(accountId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.trading.pendingOrders(accountId) });
    if (needsTradeHistory) {
      queryClient.invalidateQueries({ queryKey: queryKeys.trading.openTrades(accountId) });
    }
  }, [accountId, needsTradeHistory, queryClient]);

  const totalProfit = positions.reduce((sum, p) => sum + p.profit, 0);

  return { positions, pendingOrders, skillByTicket, openTradeByTicket, totalProfit, refresh };
}

export type AllPositions = ReturnType<typeof useAllPositions>;
