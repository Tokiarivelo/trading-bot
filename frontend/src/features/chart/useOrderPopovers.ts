"use client";

/**
 * Order-line interaction state: the right-click context menu -> pending-order
 * popover flow, the double-click-to-edit popover for a running position's
 * SL/TP/close, the SL/TP/trigger-price drag-to-modify state, and the
 * highlighted-ticket conduit shared between an external `highlightedTicket`
 * prop (from the account-wide Active Orders / Positions panel) and a
 * same-chart line click. Pure UI/interaction state — the outside-click effect
 * below closes only this hook's own two popovers (`contextMenu`/
 * `orderPopover`) via their own refs; a matching effect for
 * `drawingContextMenu`/`drawingEditPopover` stays in ChartPanel.tsx (slated
 * to move into phase 8's `useDrawingTools`), since the two pairs are opened
 * mutually exclusively by ChartPanel's `contextmenu` handler and splitting
 * the single combined effect this way is behaviorally identical.
 *
 * Not owned here: the mousemove/mouseup window listener that live-updates
 * `drag` while dragging (needs `containerRef`/`candleSeriesRef`, the chart
 * engine's own refs), the poll effect that fills `closedTrades` (needs
 * `seriesMarkersRef`/`drawingManagerRef`/`candlesRef`), and the "jump the
 * chart to a highlighted trade-history row" effect (needs `navigateToTime`/
 * `findHistoryTrade`, both bound to replay state and chart refs that live in
 * ChartPanel) — all three stay in ChartPanel.tsx and call this hook's
 * setters, the same pattern `useBacktestData` already established for the
 * backtest-report fetch effect.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { OrderSide, PendingOrderType, TradeMarker } from "@/shared/api/client";

export interface ContextMenuState {
  x: number;
  y: number;
  price: number;
  containerWidth: number;
  containerHeight: number;
}

export interface OrderPopoverState {
  x: number;
  y: number;
  price: number;
  side: OrderSide;
  orderType: PendingOrderType;
  containerWidth: number;
  containerHeight: number;
}

export interface DragState {
  key: string;
  price: number;
  commit: (p: number) => void;
}

export interface DragStartState {
  x: number;
  y: number;
  ticket: number;
  wasSelected: boolean;
}

export function useOrderPopovers(
  symbol: string,
  highlightedTicket: string | number | null,
  onSelectTicket: ((ticket: string | number, symbol: string) => void) | undefined,
) {
  // Ticket of the running position whose entry line was double-clicked, if
  // any — drives the SL/TP/close popover.
  const [editingTicket, setEditingTicket] = useState<number | null>(null);
  const [editBusy, setEditBusy] = useState(false);

  // Right-click on chart -> context menu -> pick BUY/SELL or a pending-order
  // type -> order popover.
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [orderPopover, setOrderPopover] = useState<OrderPopoverState | null>(null);

  // Root-element refs for the two popover/menu components above, scoped per
  // instance rather than a fixed global DOM id — the outside-click effect
  // below checks these instead of `document.getElementById(...)`, so
  // multiple ChartPanel instances on the same page (planned) won't collide.
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const orderPopoverRef = useRef<HTMLDivElement>(null);

  // Close context menu / order popover on click outside. The matching effect
  // for `drawingContextMenu`/`drawingEditPopover` (drawing tools' own two
  // popovers) stays in ChartPanel.tsx — see the module doc above.
  useEffect(() => {
    if (!contextMenu && !orderPopover) return;
    const handleMouseDownOutside = (e: MouseEvent) => {
      const menuEl = contextMenuRef.current;
      const popoverEl = orderPopoverRef.current;
      if (
        (menuEl && menuEl.contains(e.target as Node)) ||
        (popoverEl && popoverEl.contains(e.target as Node))
      ) {
        return;
      }
      setContextMenu(null);
      setOrderPopover(null);
    };
    window.addEventListener("mousedown", handleMouseDownOutside);
    return () => window.removeEventListener("mousedown", handleMouseDownOutside);
  }, [contextMenu, orderPopover]);

  // Ticket highlighted from a same-chart line click, when the parent isn't
  // controlling it via the `highlightedTicket` prop (see that prop's doc on
  // ChartPanel — an external caller's selection always wins).
  const [internalHighlightedTicket, setInternalHighlightedTicket] = useState<
    string | number | null
  >(null);
  const activeHighlightedTicket = highlightedTicket ?? internalHighlightedTicket;

  // This symbol's closed trades from the journal (filled by ChartPanel's
  // always-on marker poll) — looked up by ticket so a trade-history row click
  // (`activeHighlightedTicket`) can highlight its entry/SL/TP/close even
  // though it's no longer an open position.
  const [closedTrades, setClosedTrades] = useState<TradeMarker[]>([]);

  const handleTicketSelect = useCallback(
    (ticket: string | number) => {
      if (onSelectTicket) {
        onSelectTicket(ticket, symbol);
      } else {
        setInternalHighlightedTicket((prev) => (prev === ticket ? null : ticket));
      }
    },
    [onSelectTicket, symbol],
  );

  const handleTicketSelectRef = useRef(handleTicketSelect);
  handleTicketSelectRef.current = handleTicketSelect;

  // SL/TP/trigger-price draggable lines (F-manual-trading): dragging updates
  // this only for live visual feedback during the drag — the actual API call
  // fires once on mouseup, via `spec.commit` (see ChartPanel's window
  // mousemove/mouseup listener).
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef(drag);
  dragRef.current = drag;

  // Mousedown-time snapshot used by that same listener to tell a real drag
  // apart from a plain click-to-select (distance threshold).
  const dragStartRef = useRef<DragStartState | null>(null);

  return {
    editingTicket,
    setEditingTicket,
    editBusy,
    setEditBusy,
    contextMenu,
    setContextMenu,
    orderPopover,
    setOrderPopover,
    contextMenuRef,
    orderPopoverRef,
    internalHighlightedTicket,
    setInternalHighlightedTicket,
    activeHighlightedTicket,
    closedTrades,
    setClosedTrades,
    handleTicketSelect,
    handleTicketSelectRef,
    drag,
    setDrag,
    dragRef,
    dragStartRef,
  };
}

export type OrderPopovers = ReturnType<typeof useOrderPopovers>;
