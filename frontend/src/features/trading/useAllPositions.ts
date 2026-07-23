"use client";

/**
 * Account-wide (every symbol) open positions + pending orders, plus a
 * ticket -> skill lookup sourced from the journal's open trades. One shared
 * poll backs both the header's total floating P/L and the Active Orders /
 * Positions panel (including its Strategy column) instead of each polling
 * `/broker/positions` separately.
 */

import { useCallback, useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  getPendingOrders,
  getPositions,
  getTradeHistory,
  type PendingOrderOut,
  type PositionOut,
} from "@/shared/api/client";

const POLL_MS = 3000;

export function useAllPositions() {
  const accountId = useActiveAccount();
  const [positions, setPositions] = useState<PositionOut[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrderOut[]>([]);
  // Ticket (as string, matching TradeHistoryItem.id) -> bot skill id, e.g.
  // 'normal/xauusd/breakout_v1', or null for a manual/API-placed trade.
  const [skillByTicket, setSkillByTicket] = useState<Map<string, string | null>>(new Map());

  const refresh = useCallback(() => {
    if (!accountId) return; // account list not resolved yet (initial load)
    getPositions(accountId).then(setPositions).catch(() => {});
    getPendingOrders(accountId).then(setPendingOrders).catch(() => {});
    // outcome="open" scopes this to currently-open trades — 500 is the
    // endpoint's max page size, far above any realistic open-position count.
    getTradeHistory(accountId, { outcome: "open", limit: 500 })
      .then((page) => {
        setSkillByTicket(new Map(page.items.map((item) => [item.id, item.skill])));
      })
      .catch(() => {});
  }, [accountId]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const totalProfit = positions.reduce((sum, p) => sum + p.profit, 0);

  return { positions, pendingOrders, skillByTicket, totalProfit, refresh };
}

export type AllPositions = ReturnType<typeof useAllPositions>;
