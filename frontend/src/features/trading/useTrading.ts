"use client";

/**
 * Shared trading state for a symbol: polls open positions + pending orders,
 * exposes mutate actions that re-poll on success, and coordinates the
 * chart's click-to-place with the order ticket — `placementMode` is toggled
 * by the ticket, consumed by `ChartPanel`'s click handler, which populates
 * `draftOrder` for the user to confirm rather than firing an order directly.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelPendingOrder,
  closePosition,
  getPendingOrders,
  getPositions,
  modifyPendingOrder,
  modifyPosition,
  openOrder,
  placePendingOrder,
  type OrderSide,
  type PendingOrderOut,
  type PendingOrderType,
  type PositionOut,
} from "@/shared/api/client";

const POLL_MS = 3000;

export type PlacementMode = `${OrderSide}_${PendingOrderType}` | null;

export interface DraftOrder {
  side: OrderSide;
  orderType: PendingOrderType;
  price: number;
}

export function useTrading(symbol: string) {
  const [positions, setPositions] = useState<PositionOut[]>([]);
  const [pendingOrders, setPendingOrders] = useState<PendingOrderOut[]>([]);
  const [placementMode, setPlacementMode] = useState<PlacementMode>(null);
  const [draftOrder, setDraftOrder] = useState<DraftOrder | null>(null);
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  const refresh = useCallback(() => {
    if (!symbolRef.current) return; // no symbol chosen yet (initial load)
    getPositions(symbolRef.current)
      .then(setPositions)
      .catch(() => {});
    getPendingOrders(symbolRef.current)
      .then(setPendingOrders)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [symbol, refresh]);

  // A chart click while a placement mode is armed populates the draft for
  // confirmation in the ticket, then disarms itself — one click, one draft.
  const placeFromClick = useCallback(
    (price: number) => {
      if (!placementMode) return;
      const [side, orderType] = placementMode.split("_") as [OrderSide, PendingOrderType];
      setDraftOrder({ side, orderType, price });
      setPlacementMode(null);
    },
    [placementMode],
  );

  async function openMarket(
    side: OrderSide,
    volume: number,
    sl: number | null,
    tp: number | null,
  ) {
    await openOrder({ symbol, side, volume, sl, tp });
    refresh();
  }

  async function placePending(
    side: OrderSide,
    orderType: PendingOrderType,
    volume: number,
    price: number,
    sl: number | null,
    tp: number | null,
  ) {
    await placePendingOrder({ symbol, side, order_type: orderType, volume, price, sl, tp });
    setDraftOrder(null);
    refresh();
  }

  async function close(ticket: number) {
    await closePosition(ticket);
    refresh();
  }

  async function modifyPositionSlTp(ticket: number, sl: number | null, tp: number | null) {
    await modifyPosition(ticket, sl, tp);
    refresh();
  }

  async function modifyPending(
    ticket: number,
    price: number | null,
    sl: number | null,
    tp: number | null,
  ) {
    await modifyPendingOrder(ticket, price, sl, tp);
    refresh();
  }

  async function cancelPending(ticket: number) {
    await cancelPendingOrder(ticket);
    refresh();
  }

  return {
    positions,
    pendingOrders,
    placementMode,
    setPlacementMode,
    draftOrder,
    setDraftOrder,
    placeFromClick,
    openMarket,
    placePending,
    close,
    modifyPositionSlTp,
    modifyPending,
    cancelPending,
  };
}

export type Trading = ReturnType<typeof useTrading>;
