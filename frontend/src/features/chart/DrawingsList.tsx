"use client";

/**
 * DrawingsList — a compact scrollable panel listing all drawings for the
 * current symbol, with visibility toggle and delete per item.
 *
 * Rendered inside ChartPanel below the chart header when the user clicks the
 * "Drawings (N)" toggle button. The list is kept in sync by ChartPanel via
 * the React state that mirrors DrawingManager.getAllDrawings().
 */

import type { IDrawing } from "lightweight-charts-drawing";

// Human-readable labels for each tool type.
const TOOL_LABELS: Record<string, string> = {
  "trend-line":       "Trend Line",
  "extended-line":    "Extended Line",
  "horizontal-line":  "Horiz. Line",
  "vertical-line":    "Vert. Line",
  "rectangle":        "Rectangle",
  "fib-retracement":  "Fibonacci Retr.",
  "parallel-channel": "Channel",
  "circle":           "Circle",
};

// Compact SVG icons (16×16) for each tool.
function ToolIcon({ type }: { type: string }) {
  switch (type) {
    case "trend-line":
    case "extended-line":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <line x1="2" y1="13" x2="14" y2="3" />
        </svg>
      );
    case "horizontal-line":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <line x1="1" y1="8" x2="15" y2="8" />
        </svg>
      );
    case "vertical-line":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <line x1="8" y1="1" x2="8" y2="15" />
        </svg>
      );
    case "rectangle":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="4" width="12" height="8" />
        </svg>
      );
    case "fib-retracement":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.2">
          <line x1="1" y1="3" x2="15" y2="3" />
          <line x1="1" y1="8" x2="15" y2="8" />
          <line x1="1" y1="13" x2="15" y2="13" />
        </svg>
      );
    case "parallel-channel":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <line x1="1" y1="5" x2="15" y2="3" />
          <line x1="1" y1="11" x2="15" y2="9" />
        </svg>
      );
    case "circle":
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 16 16" width={14} height={14} fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="5" />
        </svg>
      );
  }
}

/** Format a price or timestamp anchor for display. */
function anchorSummary(d: IDrawing): string {
  const anchors = d.anchors;
  if (!anchors.length) return "";
  const first = anchors[0];
  const price = first.price.toFixed(5);
  return price;
}

interface Props {
  drawings: IDrawing[];
  onRemove: (id: string) => void;
  onToggleVisible: (id: string) => void;
  onColorChange: (id: string, color: string) => void;
}

export function DrawingsList({ drawings, onRemove, onToggleVisible, onColorChange }: Props) {
  if (drawings.length === 0) {
    return (
      <div
        style={{
          padding: "8px 16px",
          fontSize: 12,
          color: "var(--color-ink-muted)",
          borderBottom: "1px solid var(--color-line)",
          background: "var(--color-panel)",
        }}
      >
        No drawings on this symbol yet. Select a tool from the left toolbar to draw.
      </div>
    );
  }

  return (
    <div
      style={{
        borderBottom: "1px solid var(--color-line)",
        background: "var(--color-panel)",
        maxHeight: 160,
        overflowY: "auto",
      }}
    >
      {/* Table header */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "24px 1fr 70px 24px 24px 24px",
          gap: 4,
          padding: "4px 12px",
          fontSize: 10,
          color: "var(--color-ink-muted)",
          borderBottom: "1px solid var(--color-line)",
          position: "sticky",
          top: 0,
          background: "var(--color-panel)",
        }}
      >
        <span />
        <span>Type</span>
        <span>Price</span>
        <span title="Color">🎨</span>
        <span title="Toggle visibility">👁</span>
        <span title="Delete">✕</span>
      </div>

      {drawings.map((d) => {
        const visible = d.options.visible !== false;
        return (
          <div
            key={d.id}
            style={{
              display: "grid",
              gridTemplateColumns: "24px 1fr 70px 24px 24px 24px",
              gap: 4,
              alignItems: "center",
              padding: "3px 12px",
              fontSize: 12,
              color: visible ? "var(--color-ink)" : "var(--color-ink-muted)",
              opacity: visible ? 1 : 0.5,
              borderBottom: "1px solid var(--color-line)",
            }}
          >
            {/* Tool icon */}
            <span style={{ display: "flex", alignItems: "center", color: d.style.lineColor }}>
              <ToolIcon type={d.type} />
            </span>

            {/* Type label */}
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {TOOL_LABELS[d.type] ?? d.type}
            </span>

            {/* First anchor price */}
            <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 11 }}>
              {anchorSummary(d)}
            </span>

            {/* Color picker */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
              <input
                type="color"
                value={d.style.lineColor}
                onChange={(e) => onColorChange(d.id, e.target.value)}
                className="color-picker-input"
                style={{
                  width: 14,
                  height: 14,
                  cursor: "pointer",
                }}
                title="Change color"
              />
            </div>

            {/* Visibility toggle */}
            <button
              title={visible ? "Hide" : "Show"}
              onClick={() => onToggleVisible(d.id)}
              style={{
                width: 20,
                height: 20,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                color: visible ? "var(--color-ink)" : "var(--color-ink-muted)",
                fontSize: 12,
                padding: 0,
              }}
            >
              {visible ? "👁" : "🚫"}
            </button>

            {/* Delete */}
            <button
              title="Remove this drawing"
              onClick={() => onRemove(d.id)}
              style={{
                width: 20,
                height: 20,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                color: "var(--color-err)",
                fontSize: 11,
                padding: 0,
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
