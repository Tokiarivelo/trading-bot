"use client";

/**
 * Account-wide active orders + trade history panel, docked around the main
 * chart via OrdersDock. Unlike TradePanel (sidebar ticket, scoped to the
 * chart's current symbol), this shows every open position / pending order
 * across all symbols, plus a toggle into the full journaled history.
 *
 * Positions/pending-order data comes from `useAllPositions()` (page.tsx),
 * shared with the header's total P/L — this component only owns
 * close/cancel busy state, not the polling itself.
 */

import { useMemo, useState } from "react";
import {
  ApiError,
  cancelPendingOrder,
  closeAllPositions,
  closePosition,
  type PendingOrderOut,
  type PositionOut,
} from "@/shared/api/client";
import { TradeHistoryList } from "@/features/history/TradeHistoryList";
import { useActiveAccount } from "@/shared/api/account-context";
import { useSortableRows } from "@/shared/hooks/useSortableRows";
import { SortTh } from "@/shared/ui/SortTh";
import type { AllPositions } from "./useAllPositions";

type Tab = "active" | "history";

export function AllOrdersPanel({
  allPositions,
  selectedTicket = null,
  onSelectTicket,
  onClearSelection,
}: {
  allPositions: AllPositions;
  /** Ticket currently highlighted on the chart (see page.tsx's
   * `selectedOrderTicket`) — used to mark the matching row so the table and
   * chart stay in sync however the selection changed. */
  selectedTicket?: string | number | null;
  /** Called with a row's ticket + symbol when clicked. The caller (page.tsx)
   * owns toggling selection off on a repeat click and switching the chart to
   * that symbol if it isn't already on screen. */
  onSelectTicket?: (ticket: string | number, symbol: string) => void;
  /** Explicit clear, shown as a button next to the tabs whenever something
   * is selected — clicking the selected row again also clears it, but this
   * gives a visible way out without having to find that row again. */
  onClearSelection?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("active");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1">
        {(["active", "history"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`cursor-pointer rounded border px-2 py-1 text-xs ${
              tab === t ? "border-accent text-accent" : "border-transparent text-ink-muted"
            }`}
          >
            {t === "active" ? "Active orders" : "History"}
          </button>
        ))}
        {allPositions.positions.length > 0 && (
          <span
            className={`ml-auto rounded px-2 py-0.5 text-xs font-bold ${
              allPositions.totalProfit >= 0 ? "bg-ok text-white" : "bg-err text-white"
            }`}
            title={`Floating P/L across ${allPositions.positions.length} open position${
              allPositions.positions.length === 1 ? "" : "s"
            }`}
          >
            {allPositions.totalProfit >= 0 ? "+" : ""}
            {allPositions.totalProfit.toFixed(2)}
          </span>
        )}
        {selectedTicket !== null && (
          <button
            onClick={onClearSelection}
            className="cursor-pointer rounded border border-line px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-accent"
            title="Clear chart highlight"
          >
            × Clear selection
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "active" ? (
          <ActiveOrdersTables
            allPositions={allPositions}
            selectedTicket={selectedTicket}
            onSelectTicket={onSelectTicket}
          />
        ) : (
          <TradeHistoryList selectedTicket={selectedTicket} onSelectTicket={onSelectTicket} />
        )}
      </div>
    </div>
  );
}

type PositionSortKey =
  | "symbol"
  | "side"
  | "strategy"
  | "volume"
  | "open_price"
  | "sl"
  | "tp"
  | "profit"
  | "open_time";

type PendingSortKey = "symbol" | "side" | "order_type" | "volume" | "price" | "sl" | "tp";

function formatIsoTime(iso: string): string {
  return new Date(iso).toISOString().replace("T", " ").slice(0, 16);
}

function ActiveOrdersTables({
  allPositions,
  selectedTicket = null,
  onSelectTicket,
}: {
  allPositions: AllPositions;
  selectedTicket?: string | number | null;
  onSelectTicket?: (ticket: string | number, symbol: string) => void;
}) {
  const accountId = useActiveAccount();
  const { positions, pendingOrders, skillByTicket, refresh } = allPositions;
  const [busyTicket, setBusyTicket] = useState<number | null>(null);
  const [closingSymbol, setClosingSymbol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function skillLabel(ticket: number): string {
    const skill = skillByTicket.get(String(ticket));
    return skill ? (skill.split("/").pop() ?? skill) : "Manual";
  }

  const { sorted: sortedPositions, sort: positionSort, toggle: togglePositionSort } =
    useSortableRows<PositionOut, PositionSortKey>(
      positions,
      (p, key) => {
        switch (key) {
          case "strategy":
            return skillLabel(p.ticket);
          case "sl":
            return p.sl;
          case "tp":
            return p.tp;
          default:
            return p[key];
        }
      },
      { key: "open_time", dir: "desc" },
    );

  const { sorted: sortedPending, sort: pendingSort, toggle: togglePendingSort } =
    useSortableRows<PendingOrderOut, PendingSortKey>(
      pendingOrders,
      (o, key) => o[key],
      { key: "symbol", dir: "asc" },
    );

  const positionsBySymbol = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of positions) m.set(p.symbol, (m.get(p.symbol) ?? 0) + 1);
    return [...m.entries()];
  }, [positions]);

  async function handleClose(ticket: number) {
    if (!accountId) return;
    if (!window.confirm(`Close position #${ticket}?`)) return;
    setBusyTicket(ticket);
    setError(null);
    try {
      await closePosition(accountId, ticket);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "close failed");
    } finally {
      setBusyTicket(null);
    }
  }

  async function handleCloseAll(symbol: string, count: number) {
    if (!accountId) return;
    if (!window.confirm(`Close all ${count} ${symbol} position${count === 1 ? "" : "s"}?`)) return;
    setClosingSymbol(symbol);
    setError(null);
    try {
      await closeAllPositions(accountId, symbol);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "close-all failed");
    } finally {
      setClosingSymbol(null);
    }
  }

  async function handleCancel(ticket: number) {
    if (!accountId) return;
    setBusyTicket(ticket);
    setError(null);
    try {
      await cancelPendingOrder(accountId, ticket);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "cancel failed");
    } finally {
      setBusyTicket(null);
    }
  }

  if (positions.length === 0 && pendingOrders.length === 0 && !error) {
    return <p className="p-3 text-xs text-ink-muted">No active positions or pending orders.</p>;
  }

  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      {error && <p className="text-err">{error}</p>}
      {positions.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-ink-muted">Positions ({positions.length})</span>
            {positions.length > 1 &&
              positionsBySymbol.map(([symbol, count]) => (
                <button
                  key={symbol}
                  onClick={() => handleCloseAll(symbol, count)}
                  disabled={closingSymbol === symbol}
                  className="cursor-pointer rounded border border-line px-2 py-0.5 text-[11px] text-ink-muted hover:border-err hover:text-err disabled:opacity-50"
                  title={`Close all ${count} ${symbol} position${count === 1 ? "" : "s"}`}
                >
                  Close all {symbol} ({count})
                </button>
              ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr className="border-b border-line text-ink-muted">
                  <SortTh className="px-2 py-1" label="Symbol" sortKey="symbol" sort={positionSort} onSort={togglePositionSort} />
                  <SortTh className="px-2 py-1" label="Side" sortKey="side" sort={positionSort} onSort={togglePositionSort} />
                  <SortTh className="px-2 py-1"
                    label="Strategy"
                    sortKey="strategy"
                    sort={positionSort}
                    onSort={togglePositionSort}
                  />
                  <SortTh className="px-2 py-1"
                    label="Volume"
                    sortKey="volume"
                    sort={positionSort}
                    onSort={togglePositionSort}
                    align="right"
                  />
                  <SortTh className="px-2 py-1"
                    label="Open"
                    sortKey="open_price"
                    sort={positionSort}
                    onSort={togglePositionSort}
                    align="right"
                  />
                  <SortTh className="px-2 py-1" label="SL" sortKey="sl" sort={positionSort} onSort={togglePositionSort} align="right" />
                  <SortTh className="px-2 py-1" label="TP" sortKey="tp" sort={positionSort} onSort={togglePositionSort} align="right" />
                  <SortTh className="px-2 py-1"
                    label="P/L"
                    sortKey="profit"
                    sort={positionSort}
                    onSort={togglePositionSort}
                    align="right"
                  />
                  <SortTh className="px-2 py-1"
                    label="Opened"
                    sortKey="open_time"
                    sort={positionSort}
                    onSort={togglePositionSort}
                  />
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {sortedPositions.map((p) => {
                  const selected = selectedTicket === p.ticket;
                  return (
                    <tr
                      key={p.ticket}
                      onClick={() => onSelectTicket?.(p.ticket, p.symbol)}
                      className={`cursor-pointer border-b border-line last:border-0 ${
                        selected ? "bg-accent/10 ring-1 ring-inset ring-accent" : "hover:bg-panel/40"
                      }`}
                      title={`Highlight #${p.ticket} on the chart`}
                    >
                      <td className="px-2 py-1">{p.symbol}</td>
                      <td className={`px-2 py-1 ${p.side === "buy" ? "text-ok" : "text-err"}`}>{p.side}</td>
                      <td className="px-2 py-1 text-ink-muted" title={skillLabel(p.ticket)}>
                        {skillLabel(p.ticket)}
                      </td>
                      <td className="px-2 py-1 text-right">{p.volume}</td>
                      <td className="px-2 py-1 text-right">{p.open_price}</td>
                      <td className="px-2 py-1 text-right">{p.sl ?? "—"}</td>
                      <td className="px-2 py-1 text-right">{p.tp ?? "—"}</td>
                      <td className={`px-2 py-1 text-right ${p.profit >= 0 ? "text-ok" : "text-err"}`}>
                        {p.profit.toFixed(2)}
                      </td>
                      <td className="px-2 py-1 text-ink-muted" title={p.open_time}>
                        {formatIsoTime(p.open_time)}
                      </td>
                      <td className="px-2 py-1 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleClose(p.ticket);
                          }}
                          disabled={busyTicket === p.ticket}
                          className="cursor-pointer text-ink-muted hover:text-err disabled:opacity-50"
                          title={`Close #${p.ticket}`}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {pendingOrders.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-ink-muted">Pending orders ({pendingOrders.length})</span>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="border-b border-line text-ink-muted">
                  <SortTh className="px-2 py-1" label="Symbol" sortKey="symbol" sort={pendingSort} onSort={togglePendingSort} />
                  <SortTh className="px-2 py-1" label="Side" sortKey="side" sort={pendingSort} onSort={togglePendingSort} />
                  <SortTh className="px-2 py-1" label="Type" sortKey="order_type" sort={pendingSort} onSort={togglePendingSort} />
                  <SortTh className="px-2 py-1"
                    label="Volume"
                    sortKey="volume"
                    sort={pendingSort}
                    onSort={togglePendingSort}
                    align="right"
                  />
                  <SortTh className="px-2 py-1"
                    label="Price"
                    sortKey="price"
                    sort={pendingSort}
                    onSort={togglePendingSort}
                    align="right"
                  />
                  <SortTh className="px-2 py-1" label="SL" sortKey="sl" sort={pendingSort} onSort={togglePendingSort} align="right" />
                  <SortTh className="px-2 py-1" label="TP" sortKey="tp" sort={pendingSort} onSort={togglePendingSort} align="right" />
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {sortedPending.map((o) => {
                  const selected = selectedTicket === o.ticket;
                  return (
                    <tr
                      key={o.ticket}
                      onClick={() => onSelectTicket?.(o.ticket, o.symbol)}
                      className={`cursor-pointer border-b border-line last:border-0 ${
                        selected ? "bg-accent/10 ring-1 ring-inset ring-accent" : "hover:bg-panel/40"
                      }`}
                      title={`Highlight #${o.ticket} on the chart`}
                    >
                      <td className="px-2 py-1">{o.symbol}</td>
                      <td className={`px-2 py-1 ${o.side === "buy" ? "text-ok" : "text-err"}`}>{o.side}</td>
                      <td className="px-2 py-1">{o.order_type}</td>
                      <td className="px-2 py-1 text-right">{o.volume}</td>
                      <td className="px-2 py-1 text-right">{o.price}</td>
                      <td className="px-2 py-1 text-right">{o.sl ?? "—"}</td>
                      <td className="px-2 py-1 text-right">{o.tp ?? "—"}</td>
                      <td className="px-2 py-1 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancel(o.ticket);
                          }}
                          disabled={busyTicket === o.ticket}
                          className="cursor-pointer text-ink-muted hover:text-err disabled:opacity-50"
                          title={`Cancel #${o.ticket}`}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
