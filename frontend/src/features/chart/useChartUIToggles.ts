"use client";

/**
 * Chart display-toggle UI state: the timeframe/overlays dropdowns (with the
 * outside-click effect that closes them) and the separators/spread-line/
 * trade-labels/order-line-style/zone-color toggles from the toolbar's
 * "Overlays" menu and settings panels. Pure UI state — no chart-engine coupling.
 *
 * Known follow-up (not fixed here): the localStorage keys used below
 * (`chart-show-separators`, `chart-show-spread-line`, `chart-show-trade-labels`,
 * and `chart-order-line-style` via chartStorage.ts) are global, not scoped
 * per-symbol/per-pane — a future multi-pane feature will need to namespace
 * them.
 */

import { useEffect, useRef, useState } from "react";
import type { OrderLineStyle, ZoneColorStyle } from "./types";
import {
  loadOrderLineStyle,
  loadZoneColorStyle,
  saveOrderLineStyle,
  saveZoneColorStyle,
} from "./chartStorage";

export function useChartUIToggles() {
  const [showTfDropdown, setShowTfDropdown] = useState(false);
  const [showOverlaysDropdown, setShowOverlaysDropdown] = useState(false);
  const tfDropdownRef = useRef<HTMLDivElement>(null);
  const overlaysDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showTfDropdown && !showOverlaysDropdown) return;
    function handleOutsideClick(e: MouseEvent) {
      if (tfDropdownRef.current && !tfDropdownRef.current.contains(e.target as Node)) {
        setShowTfDropdown(false);
      }
      if (overlaysDropdownRef.current && !overlaysDropdownRef.current.contains(e.target as Node)) {
        setShowOverlaysDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [showTfDropdown, showOverlaysDropdown]);

  const [showSeparators, setShowSeparators] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-separators");
      return stored ? stored === "true" : false;
    } catch {
      return false;
    }
  });
  // Imperative mirror, read fresh inside ChartPanel's chart-render closures
  // (created once per data-load, not re-created on every state update).
  const showSeparatorsRef = useRef(showSeparators);
  showSeparatorsRef.current = showSeparators;

  function toggleSeparators(): void {
    setShowSeparators((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-separators", String(next));
      } catch {}
      return next;
    });
  }

  const [showSpreadLine, setShowSpreadLine] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-spread-line");
      return stored ? stored === "true" : false;
    } catch {
      return false;
    }
  });

  function toggleSpreadLine(): void {
    setShowSpreadLine((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-spread-line", String(next));
      } catch {}
      return next;
    });
  }

  const [showVolume, setShowVolume] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-volume");
      return stored ? stored === "true" : false;
    } catch {
      return false;
    }
  });

  function toggleVolume(): void {
    setShowVolume((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-volume", String(next));
      } catch {}
      return next;
    });
  }

  // Entry-arrow "BUY 0.01"/"SELL 0.01" text labels — off by default, as a
  // symbol with many trades stacks these into unreadable overlapping text
  // (the arrows/colors alone still show direction). Toggling this off blanks
  // just the label, the marker shape/color/position stays.
  const [showTradeLabels, setShowTradeLabels] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-trade-labels");
      return stored ? stored === "true" : false;
    } catch {
      return false;
    }
  });

  function toggleTradeLabels(): void {
    setShowTradeLabels((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-trade-labels", String(next));
      } catch {}
      return next;
    });
  }

  // The entry-arrow markers themselves — off by default. Independent of
  // `showTradeLabels` above (which only blanks the text): toggling this off
  // hides the arrow/circle shapes entirely, for reading raw price action on a
  // symbol whose chart is papered over with trade markers.
  const [showTradeMarkers, setShowTradeMarkers] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-trade-markers");
      return stored ? stored === "true" : false;
    } catch {
      return false;
    }
  });

  function toggleTradeMarkers(): void {
    setShowTradeMarkers((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-trade-markers", String(next));
      } catch {}
      return next;
    });
  }

  // Style for the selected trade's open/close lines (see
  // ChartPanel's `buildSelectedTradeLines`) — loaded once, persisted on
  // every change via chartStorage.ts.
  const [orderLineStyle, setOrderLineStyle] = useState<OrderLineStyle>(loadOrderLineStyle);
  const [showOrderLineSettings, setShowOrderLineSettings] = useState(false);

  // Per-indicator zone-rectangle colors (Quasimodo, S&D v1/v2, the per-trade
  // backend zone) — same "loaded once, persisted on every change" shape as
  // orderLineStyle above.
  const [zoneColorStyle, setZoneColorStyle] = useState<ZoneColorStyle>(loadZoneColorStyle);
  const [showZoneColorSettings, setShowZoneColorSettings] = useState(false);

  // The floating drawing-tool palette (DrawingToolbar, left edge of the
  // chart canvas) — on by default, but it can be toggled off to reclaim the
  // space when only reading the chart, without touching any drawings already
  // on it.
  const [showDrawingToolbar, setShowDrawingToolbar] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("chart-show-drawing-toolbar");
      return stored ? stored === "true" : true;
    } catch {
      return true;
    }
  });

  function toggleDrawingToolbar(): void {
    setShowDrawingToolbar((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("chart-show-drawing-toolbar", String(next));
      } catch {}
      return next;
    });
  }

  function updateOrderLineStyle(patch: Partial<OrderLineStyle>): void {
    setOrderLineStyle((prev) => {
      const next = { ...prev, ...patch };
      saveOrderLineStyle(next);
      return next;
    });
  }

  function updateZoneColorStyle(patch: Partial<ZoneColorStyle>): void {
    setZoneColorStyle((prev) => {
      const next = { ...prev, ...patch };
      saveZoneColorStyle(next);
      return next;
    });
  }

  return {
    showTfDropdown,
    setShowTfDropdown,
    showOverlaysDropdown,
    setShowOverlaysDropdown,
    tfDropdownRef,
    overlaysDropdownRef,
    showSeparators,
    showSeparatorsRef,
    toggleSeparators,
    showSpreadLine,
    toggleSpreadLine,
    showVolume,
    toggleVolume,
    showTradeLabels,
    toggleTradeLabels,
    showTradeMarkers,
    toggleTradeMarkers,
    orderLineStyle,
    updateOrderLineStyle,
    showOrderLineSettings,
    setShowOrderLineSettings,
    zoneColorStyle,
    updateZoneColorStyle,
    showZoneColorSettings,
    setShowZoneColorSettings,
    showDrawingToolbar,
    toggleDrawingToolbar,
  };
}

export type ChartUIToggles = ReturnType<typeof useChartUIToggles>;

