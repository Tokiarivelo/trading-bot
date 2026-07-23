"use client";

/** Fetches one page of filtered trade history — re-fetches page 0 whenever
 * the filters change (a new filter combination makes a stale page number
 * from the previous one meaningless), and re-fetches the same page when
 * only `page` changes (Prev/Next). */

import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  getTradeHistory,
  type TradeHistoryFilters,
  type TradeHistoryItem,
} from "@/shared/api/client";

export const PAGE_SIZE = 50;

export function useTradeHistory(filters: Omit<TradeHistoryFilters, "limit" | "offset">) {
  const accountId = useActiveAccount();
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<TradeHistoryItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const filtersKey = JSON.stringify(filters);

  useEffect(() => {
    setPage(0);
  }, [filtersKey]);

  useEffect(() => {
    if (!accountId) return;
    let cancelled = false;
    setItems(null);
    getTradeHistory(accountId, { ...filters, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then(({ items, total }) => {
        if (cancelled) return;
        setItems(items);
        setTotal(total);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        setError(e instanceof ApiError ? e.message : "failed to load trade history");
      });
    return () => {
      cancelled = true;
    };
    // filters is re-created every render by the caller; filtersKey is the
    // real dependency so this only re-fetches when it actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, filtersKey, page]);

  return { items, total, error, page, setPage, pageSize: PAGE_SIZE };
}
