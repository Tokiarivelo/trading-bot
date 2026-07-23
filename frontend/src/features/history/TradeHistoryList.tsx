"use client";

import { useMemo, useState } from "react";
import type { TradeHistoryFilters as ApiFilters } from "@/shared/api/client";
import type { GroupBy } from "./groupTrades";
import {
  EMPTY_FILTERS,
  TradeHistoryFilters,
  type TradeHistoryFilterState,
} from "./TradeHistoryFilters";
import { TradeHistoryTable } from "./TradeHistoryTable";
import { PAGE_SIZE, useTradeHistory } from "./useTradeHistory";

function toApiFilters(f: TradeHistoryFilterState): Omit<ApiFilters, "limit" | "offset"> {
  return {
    symbol: f.symbol || undefined,
    side: f.side || undefined,
    strategy_version: f.strategyVersion || undefined,
    skill: f.skill || undefined,
    outcome: f.outcome || undefined,
    open_from: f.openFrom ? Math.floor(Date.parse(`${f.openFrom}T00:00:00Z`) / 1000) : undefined,
    open_to: f.openTo ? Math.floor(Date.parse(`${f.openTo}T23:59:59Z`) / 1000) : undefined,
    order_by: f.orderBy,
    order_dir: f.orderDir,
  };
}

/** Trade history page: journaled trades across any symbol, filterable by
 * symbol/side/strategy/skill/outcome/date-range and categorizable (grouped,
 * with per-group win-rate + net P/L) by symbol, date, side, strategy
 * version, skill, or outcome. */
export function TradeHistoryList({
  selectedTicket = null,
  onSelectTicket,
}: {
  /** Ticket currently highlighted on the chart (see page.tsx's
   * `selectedOrderTicket`) — forwarded to TradeHistoryTable so a row stays
   * marked in sync with the chart however the selection changed. */
  selectedTicket?: string | number | null;
  /** Called with a row's ticket + symbol when clicked — forwarded straight
   * through from TradeHistoryTable. */
  onSelectTicket?: (ticket: string | number, symbol: string) => void;
} = {}) {
  const [filters, setFilters] = useState<TradeHistoryFilterState>(EMPTY_FILTERS);
  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const apiFilters = useMemo(() => toApiFilters(filters), [filters]);
  const { items, total, error, page, setPage } = useTradeHistory(apiFilters);

  const hasNextPage = (page + 1) * PAGE_SIZE < total;

  return (
    <div className="flex flex-col">
      <TradeHistoryFilters
        filters={filters}
        onChange={setFilters}
        groupBy={groupBy}
        onGroupByChange={setGroupBy}
      />
      {error && <p className="p-4 text-sm text-err">{error}</p>}
      {!error && items === null && <p className="p-4 text-sm text-ink-muted">Loading…</p>}
      {!error && items !== null && items.length === 0 && (
        <p className="p-4 text-sm text-ink-muted">No trades match these filters.</p>
      )}
      {!error && items !== null && items.length > 0 && (
        <TradeHistoryTable
          trades={items}
          groupBy={groupBy}
          selectedTicket={selectedTicket}
          onSelectTicket={onSelectTicket}
        />
      )}
      {!error && total > 0 && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-muted">
          <button
            type="button"
            className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            ← Prev
          </button>
          <span>
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
          </span>
          <button
            type="button"
            className="cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            onClick={() => setPage((p) => (hasNextPage ? p + 1 : p))}
            disabled={!hasNextPage}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
