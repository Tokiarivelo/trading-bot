"use client";

/**
 * Docks the account-wide AllOrdersPanel (active orders + toggleable history)
 * around the main chart. A floating toggle + position picker over the
 * chart's bottom-right corner controls visibility and which screen edge
 * (top/bottom/left/right) the panel attaches to — both persisted so they
 * survive reloads. Visible by default; a user can hide it and that choice
 * persists too. The edge facing the chart is a drag handle that resizes the
 * panel; the size is persisted separately per orientation (a horizontal dock
 * stores a height, a vertical one a width) so switching sides keeps both.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AllOrdersPanel } from "./AllOrdersPanel";
import type { AllPositions } from "./useAllPositions";

type DockPosition = "top" | "bottom" | "left" | "right";

const POSITION_KEY = "tb.ordersDock.position";
const VISIBLE_KEY = "tb.ordersDock.visible";
const HEIGHT_KEY = "tb.ordersDock.height";
const WIDTH_KEY = "tb.ordersDock.width";

const DEFAULT_HEIGHT = 280;
const DEFAULT_WIDTH = 420;
// Keep the panel usable at the small end and always leave room for the chart
// at the large end (the max is re-clamped against the real viewport on drag).
const MIN_HEIGHT = 120;
const MIN_WIDTH = 260;
const POSITIONS: { value: DockPosition; label: string }[] = [
  { value: "top", label: "Top" },
  { value: "bottom", label: "Bottom" },
  { value: "left", label: "Left" },
  { value: "right", label: "Right" },
];

function readPosition(): DockPosition {
  try {
    const stored = localStorage.getItem(POSITION_KEY);
    if (stored === "top" || stored === "bottom" || stored === "left" || stored === "right") {
      return stored;
    }
  } catch {
    // Ignore blocked localStorage — falls through to the default below.
  }
  return "bottom";
}

function readVisible(): boolean {
  try {
    const stored = localStorage.getItem(VISIBLE_KEY);
    // Visible by default — only respect an explicit prior "hide" from the
    // user (stored "0"); an absent key means they've never touched the toggle.
    return stored === null ? true : stored === "1";
  } catch {
    return true;
  }
}

function readSize(key: string, fallback: number, min: number): number {
  try {
    const stored = Number(localStorage.getItem(key));
    if (Number.isFinite(stored) && stored >= min) return stored;
  } catch {
    // Ignore blocked localStorage — falls through to the default below.
  }
  return fallback;
}

export function OrdersDock({
  children,
  allPositions,
  selectedTicket = null,
  onSelectTicket,
  onClearSelection,
  onVisibleChange,
}: {
  children: React.ReactNode;
  allPositions: AllPositions;
  /** Forwarded straight through to AllOrdersPanel — see its own prop doc. */
  selectedTicket?: string | number | null;
  onSelectTicket?: (ticket: string | number, symbol: string) => void;
  onClearSelection?: () => void;
  /**
   * Fired whenever the dock's visibility changes (including the initial
   * post-mount read of the persisted value) so a caller can gate other work
   * — e.g. `page.tsx` skips `useAllPositions`'s trade-history poll while this
   * dock (and the panel that renders it) is hidden. The dock still owns and
   * persists its own `visible` state; this is a notify-only callback, not
   * controlled-component lifting.
   */
  onVisibleChange?: (visible: boolean) => void;
}) {
  // Read persisted state after mount (not in useState initializers) so
  // server-rendered and first-client-render markup match — localStorage
  // isn't available during SSR.
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<DockPosition>("bottom");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [resizing, setResizing] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setVisible(readVisible());
    setPosition(readPosition());
    setHeight(readSize(HEIGHT_KEY, DEFAULT_HEIGHT, MIN_HEIGHT));
    setWidth(readSize(WIDTH_KEY, DEFAULT_WIDTH, MIN_WIDTH));
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(VISIBLE_KEY, visible ? "1" : "0");
    } catch {
      // Ignore blocked/full localStorage — the toggle just won't persist.
    }
    onVisibleChange?.(visible);
  }, [visible, onVisibleChange]);

  useEffect(() => {
    try {
      localStorage.setItem(POSITION_KEY, position);
    } catch {
      // Ignore blocked/full localStorage — the choice just won't persist.
    }
  }, [position]);

  useEffect(() => {
    if (!pickerOpen) return;
    const handleMouseDown = (e: MouseEvent) => {
      const el = document.getElementById("orders-dock-position-picker");
      if (el && el.contains(e.target as Node)) return;
      setPickerOpen(false);
    };
    window.addEventListener("mousedown", handleMouseDown);
    return () => window.removeEventListener("mousedown", handleMouseDown);
  }, [pickerOpen]);

  const isRow = position === "left" || position === "right";

  // Persist the size, but only once the user stops dragging — writing on every
  // pointermove would hammer localStorage at pointer-event rate.
  useEffect(() => {
    if (resizing) return;
    try {
      localStorage.setItem(HEIGHT_KEY, String(height));
      localStorage.setItem(WIDTH_KEY, String(width));
    } catch {
      // Ignore blocked/full localStorage — the size just won't persist.
    }
  }, [resizing, height, width]);

  const startResize = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const rect = panelRef.current?.getBoundingClientRect();
      if (!rect) return;
      e.preventDefault();
      setResizing(true);
      // The dock's outer edge is pinned to the layout, so measuring the
      // pointer against it gives the new size directly — no delta bookkeeping.
      const anchor = { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }[
        position
      ];

      const onMove = (ev: PointerEvent) => {
        if (position === "bottom" || position === "top") {
          const raw = position === "bottom" ? anchor - ev.clientY : ev.clientY - anchor;
          const max = Math.max(MIN_HEIGHT, window.innerHeight - 160);
          setHeight(Math.round(Math.min(max, Math.max(MIN_HEIGHT, raw))));
        } else {
          const raw = position === "right" ? anchor - ev.clientX : ev.clientX - anchor;
          const max = Math.max(MIN_WIDTH, window.innerWidth - 320);
          setWidth(Math.round(Math.min(max, Math.max(MIN_WIDTH, raw))));
        }
      };
      const onUp = () => {
        setResizing(false);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [position],
  );

  // The grab strip sits just inside the edge facing the chart (the panel is
  // `overflow-hidden`, so it can't hang outside).
  const handle = (
    <div
      onPointerDown={startResize}
      title="Drag to resize"
      className={`absolute z-10 ${
        isRow
          ? `top-0 bottom-0 w-1.5 cursor-col-resize ${position === "left" ? "right-0" : "left-0"}`
          : `left-0 right-0 h-1.5 cursor-row-resize ${position === "top" ? "bottom-0" : "top-0"}`
      } ${resizing ? "bg-accent" : "hover:bg-accent/60"}`}
    />
  );

  const panel = (
    <div
      ref={panelRef}
      style={isRow ? { width } : { height }}
      className={
        isRow
          ? `relative flex flex-shrink-0 flex-col overflow-hidden border-line bg-panel ${
              position === "left" ? "border-r" : "border-l"
            }`
          : `relative flex flex-shrink-0 flex-col overflow-hidden border-line bg-panel ${
              position === "top" ? "border-b" : "border-t"
            }`
      }
    >
      {handle}
      <AllOrdersPanel
        allPositions={allPositions}
        selectedTicket={selectedTicket}
        onSelectTicket={onSelectTicket}
        onClearSelection={onClearSelection}
      />
    </div>
  );

  return (
    <div className={`flex min-h-0 flex-1 ${isRow ? "flex-row" : "flex-col"}`}>
      {visible && (position === "left" || position === "top") && panel}
      <div className="relative flex min-h-0 flex-1 flex-col">
        {children}
        <div className="pointer-events-none absolute bottom-2 right-2 z-20 flex items-center gap-1">
          <button
            onClick={() => setVisible((v) => !v)}
            className={`pointer-events-auto cursor-pointer rounded border px-2 py-1 text-xs shadow ${
              visible ? "border-accent text-accent bg-panel" : "border-line text-ink-muted bg-panel"
            }`}
            title="Show / hide active orders & history"
          >
            Orders
          </button>
          <div id="orders-dock-position-picker" className="pointer-events-auto relative">
            <button
              onClick={() => setPickerOpen((v) => !v)}
              className="cursor-pointer rounded border border-line bg-panel px-2 py-1 text-xs text-ink-muted shadow"
              title="Choose panel position"
            >
              ⚙
            </button>
            {pickerOpen && (
              <div className="absolute bottom-full right-0 mb-1 flex w-24 flex-col rounded border border-line bg-panel py-1 text-xs shadow-xl">
                {POSITIONS.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => {
                      setPosition(p.value);
                      setPickerOpen(false);
                    }}
                    className={`cursor-pointer px-3 py-1 text-left hover:bg-line ${
                      position === p.value ? "text-accent" : "text-ink"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      {visible && (position === "right" || position === "bottom") && panel}
    </div>
  );
}
