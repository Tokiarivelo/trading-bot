"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getBotAnalytics,
  getSymbolAnalytics,
  type BotAnalytics,
  type SymbolAnalytics,
} from "@/shared/api/client";
import { useActiveAccount } from "@/shared/api/account-context";

/** Loads both analytics breakdowns together — the page renders symbol
 * stats, bot stats, and the equity-curve chart from the same fetch, so one
 * hook keeps their loading/error/refresh state in sync instead of three
 * components racing independent requests. */
export function useAnalytics() {
  const accountId = useActiveAccount();
  const [symbols, setSymbols] = useState<SymbolAnalytics[]>([]);
  const [bots, setBots] = useState<BotAnalytics[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    Promise.all([getSymbolAnalytics(accountId), getBotAnalytics(accountId)])
      .then(([symbolData, botData]) => {
        setSymbols(symbolData);
        setBots(botData);
      })
      .catch(() => setError("Failed to load analytics."))
      .finally(() => setLoading(false));
  }, [accountId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { symbols, bots, loading, error, refresh };
}
