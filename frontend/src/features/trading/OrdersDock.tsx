"use client";

/**
 * Docks the account-wide AllOrdersPanel (active orders + toggleable history)
 * around the main chart. A floating toggle + position picker over the
 * chart's bottom-right corner controls visibility and which screen edge
 * (top/bottom/left/right) the panel attaches to — both persisted so they
 * survive reloads. Visible by default; a user can hide it and that choice
 * persists too.
 */

import { useEffect, useState } from "react";
import { AllOrdersPanel } from "./AllOrdersPanel";
import type { AllPositions } from "./useAllPositions";

type DockPosition = "top" | "bottom" | "left" | "right";

const POSITION_KEY = "tb.ordersDock.position";
const VISIBLE_KEY = "tb.ordersDock.visible";
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

export function OrdersDock({
  children,
  allPositions,
  selectedTicket = null,
  onSelectTicket,
  onClearSelection,
}: {
  children: React.ReactNode;
  allPositions: AllPositions;
  /** Forwarded straight through to AllOrdersPanel — see its own prop doc. */
  selectedTicket?: string | number | null;
  onSelectTicket?: (ticket: string | number, symbol: string) => void;
  onClearSelection?: () => void;
}) {
  // Read persisted state after mount (not in useState initializers) so
  // server-rendered and first-client-render markup match — localStorage
  // isn't available during SSR.
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<DockPosition>("bottom");
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    setVisible(readVisible());
    setPosition(readPosition());
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(VISIBLE_KEY, visible ? "1" : "0");
    } catch {
      // Ignore blocked/full localStorage — the toggle just won't persist.
    }
  }, [visible]);

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

  const panel = (
    <div
      className={
        isRow
          ? `flex w-[420px] flex-shrink-0 flex-col overflow-hidden border-line bg-panel ${
              position === "left" ? "border-r" : "border-l"
            }`
          : `flex h-[280px] flex-shrink-0 flex-col overflow-hidden border-line bg-panel ${
              position === "top" ? "border-b" : "border-t"
            }`
      }
    >
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
