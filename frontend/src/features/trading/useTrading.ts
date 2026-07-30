"use client";

/**
 * Symbol-scoped trading state, derived from `useAllPositions`'s already-
 * polled account-wide result rather than polling `getPositions`/
 * `getPendingOrders` a second time — `positions`/`pendingOrders` here are
 * just that account-wide result filtered down to `symbol` (see `AllPositions`
 * in `useAllPositions.ts`, the single caller-shared TanStack Query cache).
 * Mutate actions are `useMutation`s whose `onSuccess` calls
 * `allPositions.refresh()` — the same account-scoped query-key invalidation
 * `refresh()` already does for the manual "refresh now" case — so a change
 * reflects immediately rather than waiting for the next poll tick. Also
 * coordinates the chart's click-to-place with the order ticket —
 * `placementMode` is toggled by the ticket, consumed by `ChartPanel`'s click
 * handler, which populates `draftOrder` for the user to confirm rather than
 * firing an order directly.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  cancelPendingOrder,
  closePosition,
  modifyPendingOrder,
  modifyPosition,
  openOrder,
  placePendingOrder,
  type OrderSide,
  type PendingOrderType,
} from "@/shared/api/client";
import type { AllPositions } from "./useAllPositions";

export type PlacementMode = `${OrderSide}_${PendingOrderType}` | null;

export interface DraftOrder {
  side: OrderSide;
  orderType: PendingOrderType;
  price: number;
}

export function useTrading(symbol: string, allPositions: AllPositions) {
  const accountId = useActiveAccount();
  const [placementMode, setPlacementMode] = useState<PlacementMode>(null);
  const [draftOrder, setDraftOrder] = useState<DraftOrder | null>(null);
  const accountIdRef = useRef(accountId);
  accountIdRef.current = accountId;
  const refresh = allPositions.refresh;

  const positions = useMemo(
    () => allPositions.positions.filter((p) => p.symbol === symbol),
    [allPositions.positions, symbol],
  );
  const pendingOrders = useMemo(
    () => allPositions.pendingOrders.filter((o) => o.symbol === symbol),
    [allPositions.pendingOrders, symbol],
  );

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

  const openMarketMutation = useMutation({
    mutationFn: (vars: { account: string; side: OrderSide; volume: number; sl: number | null; tp: number | null }) =>
      openOrder(vars.account, { symbol, side: vars.side, volume: vars.volume, sl: vars.sl, tp: vars.tp }),
    onSuccess: () => refresh(),
  });

  const placePendingMutation = useMutation({
    mutationFn: (vars: {
      account: string;
      side: OrderSide;
      orderType: PendingOrderType;
      volume: number;
      price: number;
      sl: number | null;
      tp: number | null;
    }) =>
      placePendingOrder(vars.account, {
        symbol,
        side: vars.side,
        order_type: vars.orderType,
        volume: vars.volume,
        price: vars.price,
        sl: vars.sl,
        tp: vars.tp,
      }),
    onSuccess: () => {
      setDraftOrder(null);
      refresh();
    },
  });

  const closeMutation = useMutation({
    mutationFn: (vars: { account: string; ticket: number }) => closePosition(vars.account, vars.ticket),
    onSuccess: () => refresh(),
  });

  const modifyPositionSlTpMutation = useMutation({
    mutationFn: (vars: { account: string; ticket: number; sl: number | null; tp: number | null }) =>
      modifyPosition(vars.account, vars.ticket, vars.sl, vars.tp),
    onSuccess: () => refresh(),
  });

  const modifyPendingMutation = useMutation({
    mutationFn: (vars: {
      account: string;
      ticket: number;
      price: number | null;
      sl: number | null;
      tp: number | null;
    }) => modifyPendingOrder(vars.account, vars.ticket, vars.price, vars.sl, vars.tp),
    onSuccess: () => refresh(),
  });

  const cancelPendingMutation = useMutation({
    mutationFn: (vars: { account: string; ticket: number }) => cancelPendingOrder(vars.account, vars.ticket),
    onSuccess: () => refresh(),
  });

  async function openMarket(
    side: OrderSide,
    volume: number,
    sl: number | null,
    tp: number | null,
  ) {
    const account = accountIdRef.current;
    if (!account) return;
    await openMarketMutation.mutateAsync({ account, side, volume, sl, tp });
  }

  async function placePending(
    side: OrderSide,
    orderType: PendingOrderType,
    volume: number,
    price: number,
    sl: number | null,
    tp: number | null,
  ) {
    const account = accountIdRef.current;
    if (!account) return;
    await placePendingMutation.mutateAsync({ account, side, orderType, volume, price, sl, tp });
  }

  async function close(ticket: number) {
    const account = accountIdRef.current;
    if (!account) return;
    await closeMutation.mutateAsync({ account, ticket });
  }

  async function modifyPositionSlTp(ticket: number, sl: number | null, tp: number | null) {
    const account = accountIdRef.current;
    if (!account) return;
    await modifyPositionSlTpMutation.mutateAsync({ account, ticket, sl, tp });
  }

  async function modifyPending(
    ticket: number,
    price: number | null,
    sl: number | null,
    tp: number | null,
  ) {
    const account = accountIdRef.current;
    if (!account) return;
    await modifyPendingMutation.mutateAsync({ account, ticket, price, sl, tp });
  }

  async function cancelPending(ticket: number) {
    const account = accountIdRef.current;
    if (!account) return;
    await cancelPendingMutation.mutateAsync({ account, ticket });
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
