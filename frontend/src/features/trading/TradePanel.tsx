"use client";

/**
 * Manual trading ticket: market buy/sell buttons, a limit/stop pending-order
 * form (price can come from typing or from a chart click via `placeFromClick`
 * — see useTrading), and a list of open positions / pending orders for the
 * symbol with inline close/cancel. SL/TP are optional everywhere — the
 * backend's RR gate only runs when both are set (`SpreadGate`), so a naked
 * position/order is a deliberate, allowed choice, not an error.
 *
 * Market buy/sell fires immediately on click, no confirmation step — the
 * click itself is the deliberate action; closing a position still confirms
 * since that's undoing an existing trade, not placing a new one.
 */

import { useEffect, useState } from "react";
import type { OrderSide, PendingOrderType, PendingOrderOut, PositionOut } from "@/shared/api/client";
import type { Trading } from "./useTrading";

function numOrNull(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Reliable text-entry alternative to dragging the chart's SL/TP lines —
 * same effect, since both call `modifyPositionSlTp`. */
function PositionRow({
  position,
  busy,
  onModify,
  onClose,
}: {
  position: PositionOut;
  busy: boolean;
  onModify: (sl: number | null, tp: number | null) => void;
  onClose: () => void;
}) {
  const [sl, setSl] = useState(position.sl === null ? "" : String(position.sl));
  const [tp, setTp] = useState(position.tp === null ? "" : String(position.tp));

  return (
    <div className="flex flex-col gap-0.5 text-xs">
      <div className="flex items-center justify-between gap-1">
        <span className={position.side === "buy" ? "text-ok" : "text-err"}>
          {position.side} {position.volume} @ {position.open_price}
        </span>
        <span className={position.profit >= 0 ? "text-ok" : "text-err"}>
          {position.profit.toFixed(2)}
        </span>
        <button
          onClick={onClose}
          disabled={busy}
          className="cursor-pointer text-ink-muted hover:text-err"
          title={`Close #${position.ticket}`}
        >
          ×
        </button>
      </div>
      <div className="flex gap-1">
        <input
          className="w-16 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={sl}
          onChange={(e) => setSl(e.target.value)}
          placeholder="SL"
        />
        <input
          className="w-16 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={tp}
          onChange={(e) => setTp(e.target.value)}
          placeholder="TP"
        />
        <button
          onClick={() => onModify(numOrNull(sl), numOrNull(tp))}
          disabled={busy}
          className="cursor-pointer rounded border border-line px-1 text-ink-muted hover:border-accent hover:text-accent"
        >
          Set
        </button>
      </div>
    </div>
  );
}

function PendingOrderRow({
  order,
  busy,
  onModify,
  onCancel,
}: {
  order: PendingOrderOut;
  busy: boolean;
  onModify: (sl: number | null, tp: number | null) => void;
  onCancel: () => void;
}) {
  const [sl, setSl] = useState(order.sl === null ? "" : String(order.sl));
  const [tp, setTp] = useState(order.tp === null ? "" : String(order.tp));

  return (
    <div className="flex flex-col gap-0.5 text-xs">
      <div className="flex items-center justify-between gap-1">
        <span className={order.side === "buy" ? "text-ok" : "text-err"}>
          {order.side} {order.order_type} {order.volume} @ {order.price}
        </span>
        <button
          onClick={onCancel}
          disabled={busy}
          className="cursor-pointer text-ink-muted hover:text-err"
          title={`Cancel #${order.ticket}`}
        >
          ×
        </button>
      </div>
      <div className="flex gap-1">
        <input
          className="w-16 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={sl}
          onChange={(e) => setSl(e.target.value)}
          placeholder="SL"
        />
        <input
          className="w-16 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={tp}
          onChange={(e) => setTp(e.target.value)}
          placeholder="TP"
        />
        <button
          onClick={() => onModify(numOrNull(sl), numOrNull(tp))}
          disabled={busy}
          className="cursor-pointer rounded border border-line px-1 text-ink-muted hover:border-accent hover:text-accent"
        >
          Set
        </button>
      </div>
    </div>
  );
}

export function TradePanel({ symbol, trading }: { symbol: string; trading: Trading }) {
  const [volume, setVolume] = useState("0.01");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [pendingSide, setPendingSide] = useState<OrderSide>("buy");
  const [pendingType, setPendingType] = useState<PendingOrderType>("limit");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A chart click (armed via "Set price on chart") fills in this ticket.
  useEffect(() => {
    if (!trading.draftOrder) return;
    setPendingSide(trading.draftOrder.side);
    setPendingType(trading.draftOrder.orderType);
    setPrice(String(trading.draftOrder.price));
  }, [trading.draftOrder]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "order failed");
    } finally {
      setBusy(false);
    }
  }

  function handleMarket(side: OrderSide) {
    const v = Number(volume);
    if (!v) {
      setError("volume is required");
      return;
    }
    run(() => trading.openMarket(side, v, numOrNull(sl), numOrNull(tp)));
  }

  function handlePlacePending() {
    const v = Number(volume);
    const p = Number(price);
    if (!v || !p) {
      setError("volume and price are required for a pending order");
      return;
    }
    if (!window.confirm(`${pendingSide.toUpperCase()} ${pendingType} ${v} lots ${symbol} @ ${p}?`))
      return;
    run(() => trading.placePending(pendingSide, pendingType, v, p, numOrNull(sl), numOrNull(tp)));
  }

  function armPlacementMode(side: OrderSide, type: PendingOrderType) {
    setPendingSide(side);
    setPendingType(type);
    trading.setPlacementMode(`${side}_${type}`);
  }

  async function handleClose(ticket: number) {
    if (!window.confirm(`Close position #${ticket}?`)) return;
    await run(() => trading.close(ticket));
  }

  async function handleCancel(ticket: number) {
    await run(() => trading.cancelPending(ticket));
  }

  return (
    <div className="flex flex-col gap-3 text-sm">
      {error && <p className="text-xs text-err">{error}</p>}

      <div className="flex gap-2">
        <input
          className="w-20 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={volume}
          onChange={(e) => setVolume(e.target.value)}
          placeholder="lots"
        />
        <input
          className="w-24 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={sl}
          onChange={(e) => setSl(e.target.value)}
          placeholder="SL (optional)"
        />
        <input
          className="w-24 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
          value={tp}
          onChange={(e) => setTp(e.target.value)}
          placeholder="TP (optional)"
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => handleMarket("buy")}
          disabled={busy}
          className="flex-1 cursor-pointer rounded bg-ok px-2 py-1 font-bold text-[#04211e] disabled:opacity-50"
        >
          Buy
        </button>
        <button
          onClick={() => handleMarket("sell")}
          disabled={busy}
          className="flex-1 cursor-pointer rounded bg-err px-2 py-1 font-bold text-[#2b0808] disabled:opacity-50"
        >
          Sell
        </button>
      </div>

      <div className="flex flex-col gap-1 border-t border-line pt-2">
        <span className="text-xs text-ink-muted">Pending order</span>
        <div className="flex gap-1">
          {(["buy", "sell"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setPendingSide(s)}
              className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
                pendingSide === s ? "border-accent text-accent" : "border-line text-ink-muted"
              }`}
            >
              {s}
            </button>
          ))}
          {(["limit", "stop"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setPendingType(t)}
              className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
                pendingType === t ? "border-accent text-accent" : "border-line text-ink-muted"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            className="w-24 rounded border border-line bg-transparent px-1 py-0.5 text-xs"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="trigger price"
          />
          <button
            onClick={() => armPlacementMode(pendingSide, pendingType)}
            className={`cursor-pointer rounded border px-2 py-0.5 text-xs ${
              trading.placementMode === `${pendingSide}_${pendingType}`
                ? "border-accent text-accent"
                : "border-line text-ink-muted"
            }`}
            title="Click a price on the chart to fill this in"
          >
            {trading.placementMode === `${pendingSide}_${pendingType}`
              ? "Click chart…"
              : "Set price on chart"}
          </button>
        </div>
        <button
          onClick={handlePlacePending}
          disabled={busy}
          className="cursor-pointer rounded border border-accent px-2 py-1 text-xs text-accent disabled:opacity-50"
        >
          Place {pendingSide} {pendingType}
        </button>
      </div>

      {trading.positions.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-line pt-2">
          <span className="text-xs text-ink-muted">Open positions</span>
          {trading.positions.map((p) => (
            <div key={p.ticket} className="flex items-center justify-between gap-1 text-xs">
              <span className={p.side === "buy" ? "text-ok" : "text-err"}>
                {p.side} {p.volume} @ {p.open_price}
              </span>
              <span className={p.profit >= 0 ? "text-ok" : "text-err"}>{p.profit.toFixed(2)}</span>
              <button
                onClick={() => handleClose(p.ticket)}
                disabled={busy}
                className="cursor-pointer text-ink-muted hover:text-err"
                title={`Close #${p.ticket}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {trading.pendingOrders.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-line pt-2">
          <span className="text-xs text-ink-muted">Pending orders</span>
          {trading.pendingOrders.map((o) => (
            <div key={o.ticket} className="flex items-center justify-between gap-1 text-xs">
              <span className={o.side === "buy" ? "text-ok" : "text-err"}>
                {o.side} {o.order_type} {o.volume} @ {o.price}
              </span>
              <button
                onClick={() => handleCancel(o.ticket)}
                disabled={busy}
                className="cursor-pointer text-ink-muted hover:text-err"
                title={`Cancel #${o.ticket}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
