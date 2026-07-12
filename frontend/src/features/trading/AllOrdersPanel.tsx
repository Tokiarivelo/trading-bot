"use client";

/**
 * Account-wide active orders + trade history panel, docked around the main
 * chart via OrdersDock. Unlike TradePanel (sidebar ticket, scoped to the
 * chart's current symbol), this shows every open position / pending order
 * across all symbols, plus a toggle into the full journaled history.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  cancelPendingOrder,
  closePosition,
  getPendingOrders,
  getPositions,
  type PendingOrderOut,
  type PositionOut,
} from "@/shared/api/client";
import { TradeHistoryList } from "@/features/history/TradeHistoryList";

const POLL_MS = 3000;

type Tab = "active" | "history";

export function AllOrdersPanel() {
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
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "active" ? <ActiveOrdersTables /> : <TradeHistoryList />}
      </div>
    </div>
  );
}

function ActiveOrdersTables() {
  const [positions, setPositions] = useState<PositionOut[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrderOut[]>([]);
  const [busyTicket, setBusyTicket] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // No symbol filter passed — getPositions()/getPendingOrders() return
  // every open position/pending order across the whole account.
  const refresh = useCallback(() => {
    getPositions().then(setPositions).catch(() => {});
    getPendingOrders().then(setPendingOrders).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  async function handleClose(ticket: number) {
    if (!window.confirm(`Close position #${ticket}?`)) return;
    setBusyTicket(ticket);
    setError(null);
    try {
      await closePosition(ticket);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "close failed");
    } finally {
      setBusyTicket(null);
    }
  }

  async function handleCancel(ticket: number) {
    setBusyTicket(ticket);
    setError(null);
    try {
      await cancelPendingOrder(ticket);
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
          <span className="text-ink-muted">Positions ({positions.length})</span>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="border-b border-line text-left text-ink-muted">
                  <th className="px-2 py-1">Symbol</th>
                  <th className="px-2 py-1">Side</th>
                  <th className="px-2 py-1 text-right">Volume</th>
                  <th className="px-2 py-1 text-right">Open</th>
                  <th className="px-2 py-1 text-right">SL</th>
                  <th className="px-2 py-1 text-right">TP</th>
                  <th className="px-2 py-1 text-right">P/L</th>
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.ticket} className="border-b border-line last:border-0 hover:bg-panel/40">
                    <td className="px-2 py-1">{p.symbol}</td>
                    <td className={`px-2 py-1 ${p.side === "buy" ? "text-ok" : "text-err"}`}>{p.side}</td>
                    <td className="px-2 py-1 text-right">{p.volume}</td>
                    <td className="px-2 py-1 text-right">{p.open_price}</td>
                    <td className="px-2 py-1 text-right">{p.sl ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{p.tp ?? "—"}</td>
                    <td className={`px-2 py-1 text-right ${p.profit >= 0 ? "text-ok" : "text-err"}`}>
                      {p.profit.toFixed(2)}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <button
                        onClick={() => handleClose(p.ticket)}
                        disabled={busyTicket === p.ticket}
                        className="cursor-pointer text-ink-muted hover:text-err disabled:opacity-50"
                        title={`Close #${p.ticket}`}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
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
                <tr className="border-b border-line text-left text-ink-muted">
                  <th className="px-2 py-1">Symbol</th>
                  <th className="px-2 py-1">Side</th>
                  <th className="px-2 py-1">Type</th>
                  <th className="px-2 py-1 text-right">Volume</th>
                  <th className="px-2 py-1 text-right">Price</th>
                  <th className="px-2 py-1 text-right">SL</th>
                  <th className="px-2 py-1 text-right">TP</th>
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {pendingOrders.map((o) => (
                  <tr key={o.ticket} className="border-b border-line last:border-0 hover:bg-panel/40">
                    <td className="px-2 py-1">{o.symbol}</td>
                    <td className={`px-2 py-1 ${o.side === "buy" ? "text-ok" : "text-err"}`}>{o.side}</td>
                    <td className="px-2 py-1">{o.order_type}</td>
                    <td className="px-2 py-1 text-right">{o.volume}</td>
                    <td className="px-2 py-1 text-right">{o.price}</td>
                    <td className="px-2 py-1 text-right">{o.sl ?? "—"}</td>
                    <td className="px-2 py-1 text-right">{o.tp ?? "—"}</td>
                    <td className="px-2 py-1 text-right">
                      <button
                        onClick={() => handleCancel(o.ticket)}
                        disabled={busyTicket === o.ticket}
                        className="cursor-pointer text-ink-muted hover:text-err disabled:opacity-50"
                        title={`Cancel #${o.ticket}`}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
