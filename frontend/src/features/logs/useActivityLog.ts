"use client";

/** Fetches one page of filtered activity log entries — re-fetches page 0
 * whenever the filters change, and re-fetches the same page when only
 * `page` changes (Prev/Next). Mirrors `features/history/useTradeHistory.ts`. */

import { useEffect, useState } from "react";
import {
  ApiError,
  getActivityLog,
  type LogEntry,
  type LogHistoryFilters,
} from "@/shared/api/client";

export const PAGE_SIZE = 100;

const AUTO_REFRESH_INTERVAL_MS = 5000;

export function useActivityLog(
  filters: Omit<LogHistoryFilters, "limit" | "offset">,
  autoRefresh: boolean = false
) {
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<LogEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [manualRefresh, setManualRefresh] = useState(0);
  const filtersKey = JSON.stringify(filters);

  useEffect(() => {
    setPage(0);
  }, [filtersKey]);

  // Only page 0 is "live" — the newest entries land there (newest-first
  // sort), so ticking on any other page would silently shift the reader's
  // view out from under them.
  useEffect(() => {
    if (!autoRefresh || page !== 0) return;
    const id = setInterval(() => setTick((t) => t + 1), AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [autoRefresh, page]);

  useEffect(() => {
    let cancelled = false;
    if (tick === 0) setItems(null);
    getActivityLog({ ...filters, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
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
        setError(e instanceof ApiError ? e.message : "failed to load activity log");
      });
    return () => {
      cancelled = true;
    };
    // filters is re-created every render by the caller; filtersKey is the
    // real dependency so this only re-fetches when it actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, page, tick, manualRefresh]);

  return {
    items,
    total,
    error,
    page,
    setPage,
    pageSize: PAGE_SIZE,
    refresh: () => setManualRefresh((n) => n + 1),
  };
}
