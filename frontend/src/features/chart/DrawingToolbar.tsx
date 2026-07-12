"use client";

/**
 * DrawingToolbar — TradingView-style floating toolbar for chart drawing tools.
 *
 * Renders a compact vertical strip on the left edge of the chart area.
 * Each button activates a `lightweight-charts-drawing` tool type string that
 * is forwarded to `DrawingManager.setActiveTool()` in ChartPanel.
 *
 * Pressing the same active button again deactivates drawing mode (toggles off).
 */

import { useState } from "react";
import type { DrawingToolType } from "./ChartPanel";

const PRESET_COLORS = [
  "#2962ff", // Blue
  "#26a69a", // Green
  "#ef5350", // Red
  "#ff9800", // Orange
  "#9c27b0", // Purple
  "#ffffff", // White
];


interface ToolDef {
  type: DrawingToolType;
  label: string;
  title: string;
  /** SVG path(s) for the 16×16 icon */
  icon: React.ReactNode;
}

const TOOLS: ToolDef[] = [
  {
    type: "trend-line",
    label: "TL",
    title: "Trend Line — click two points",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <line x1="2" y1="13" x2="14" y2="3" />
        <circle cx="2" cy="13" r="1.5" fill="currentColor" stroke="none" />
        <circle cx="14" cy="3" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    type: "extended-line",
    label: "EL",
    title: "Extended Line (Ray) — extends infinitely",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <line x1="1" y1="13" x2="15" y2="3" strokeDasharray="2 1" />
        <circle cx="4" cy="11" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    type: "horizontal-line",
    label: "HL",
    title: "Horizontal Line — click one price level",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <line x1="1" y1="8" x2="15" y2="8" />
        <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    type: "vertical-line",
    label: "VL",
    title: "Vertical Line — click one time point",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <line x1="8" y1="1" x2="8" y2="15" />
        <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  {
    type: "rectangle",
    label: "RE",
    title: "Rectangle — click two corners",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="4" width="12" height="8" rx="0.5" />
      </svg>
    ),
  },
  {
    type: "fib-retracement",
    label: "FB",
    title: "Fibonacci Retracement — click swing high & low",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2">
        <line x1="1" y1="3" x2="15" y2="3" />
        <line x1="1" y1="6" x2="15" y2="6" strokeOpacity="0.7" />
        <line x1="1" y1="8" x2="15" y2="8" />
        <line x1="1" y1="10" x2="15" y2="10" strokeOpacity="0.7" />
        <line x1="1" y1="13" x2="15" y2="13" />
        <text x="1" y="5.5" fontSize="2.5" fill="currentColor" stroke="none" opacity="0.8">1</text>
        <text x="1" y="8.5" fontSize="2.5" fill="currentColor" stroke="none" opacity="0.8">.5</text>
        <text x="1" y="14.5" fontSize="2.5" fill="currentColor" stroke="none" opacity="0.8">0</text>
      </svg>
    ),
  },
  {
    type: "parallel-channel",
    label: "CH",
    title: "Parallel Channel — click two points then width",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <line x1="1" y1="5" x2="15" y2="3" />
        <line x1="1" y1="11" x2="15" y2="9" />
        <line x1="1" y1="5" x2="1" y2="11" strokeWidth="0.8" strokeDasharray="2 1" />
        <line x1="15" y1="3" x2="15" y2="9" strokeWidth="0.8" strokeDasharray="2 1" />
      </svg>
    ),
  },
];

interface Props {
  activeTool: DrawingToolType | null;
  onToolSelect: (tool: DrawingToolType | null) => void;
  onClearAll: () => void;
  activeColor: string;
  onColorChange: (color: string) => void;
}

export function DrawingToolbar({
  activeTool,
  onToolSelect,
  onClearAll,
  activeColor,
  onColorChange,
}: Props) {
  const [showColorPicker, setShowColorPicker] = useState(false);

  function handleClick(type: DrawingToolType) {
    // Toggle: clicking the active tool again deactivates drawing mode
    onToolSelect(activeTool === type ? null : type);
  }

  return (
    <div
      className="pointer-events-auto absolute left-1 top-1 z-20 flex flex-col gap-0.5 rounded border border-line bg-panel shadow-xl"
      style={{ padding: "3px" }}
    >
      {TOOLS.map((tool) => {
        const isActive = activeTool === tool.type;
        return (
          <button
            key={tool.type}
            title={tool.title}
            onClick={() => handleClick(tool.type)}
            className="cursor-pointer rounded transition-all duration-100"
            style={{
              width: 28,
              height: 28,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: isActive ? "var(--color-accent)" : "transparent",
              color: isActive ? "#fff" : "var(--color-ink-muted)",
              border: isActive ? "1px solid var(--color-accent)" : "1px solid transparent",
            }}
            onMouseEnter={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                  "var(--color-line)";
                (e.currentTarget as HTMLButtonElement).style.color =
                  "var(--color-ink)";
              }
            }}
            onMouseLeave={(e) => {
              if (!isActive) {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                  "transparent";
                (e.currentTarget as HTMLButtonElement).style.color =
                  "var(--color-ink-muted)";
              }
            }}
          >
            <span style={{ width: 16, height: 16, display: "flex" }}>
              {tool.icon}
            </span>
          </button>
        );
      })}

      {/* Divider */}
      <div style={{ height: 1, backgroundColor: "var(--color-line)", margin: "2px 0" }} />

      {/* Clear all */}
      <button
        title="Clear all drawings for this symbol"
        onClick={onClearAll}
        className="cursor-pointer rounded transition-all duration-100"
        style={{
          width: 28,
          height: 28,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "transparent",
          color: "var(--color-err)",
          border: "1px solid transparent",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.backgroundColor =
            "rgba(239,83,80,0.15)";
          (e.currentTarget as HTMLButtonElement).style.borderColor =
            "var(--color-err)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.backgroundColor =
            "transparent";
          (e.currentTarget as HTMLButtonElement).style.borderColor = "transparent";
        }}
      >
        <svg viewBox="0 0 16 16" width={16} height={16} fill="none" stroke="currentColor" strokeWidth="1.5">
          <polyline points="3,5 13,5" />
          <path d="M6 5V3h4v2" />
          <rect x="4" y="5" width="8" height="8" rx="1" />
          <line x1="6" y1="8" x2="6" y2="11" />
          <line x1="10" y1="8" x2="10" y2="11" />
        </svg>
      </button>

      {/* Divider */}
      <div style={{ height: 1, backgroundColor: "var(--color-line)", margin: "2px 0" }} />

      {/* Active Color Picker */}
      <div className="relative flex justify-center">
        <button
          title="Choose Drawing Color"
          onClick={() => setShowColorPicker(!showColorPicker)}
          className="cursor-pointer rounded transition-all duration-100"
          style={{
            width: 28,
            height: 28,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: showColorPicker ? "var(--color-line)" : "transparent",
            border: "1px solid transparent",
          }}
          onMouseEnter={(e) => {
            if (!showColorPicker) {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "var(--color-line)";
            }
          }}
          onMouseLeave={(e) => {
            if (!showColorPicker) {
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = "transparent";
            }
          }}
        >
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              backgroundColor: activeColor,
              border: "1.5px solid var(--color-ink)",
              boxShadow: "0 0 2px rgba(0,0,0,0.5)",
            }}
          />
        </button>

        {showColorPicker && (
          <div
            className="absolute left-9 top-0 z-30 flex items-center gap-1.5 rounded border border-line bg-panel p-2 shadow-2xl"
            style={{ whiteSpace: "nowrap" }}
          >
            {PRESET_COLORS.map((c) => (
              <button
                key={c}
                onClick={() => {
                  onColorChange(c);
                  setShowColorPicker(false);
                }}
                className="cursor-pointer rounded-full border border-line hover:scale-110 transition-transform"
                style={{
                  width: 18,
                  height: 18,
                  backgroundColor: c,
                }}
                title={c}
              />
            ))}
            <div style={{ width: 1, height: 18, backgroundColor: "var(--color-line)", margin: "0 2px" }} />
            <input
              type="color"
              value={activeColor}
              onChange={(e) => onColorChange(e.target.value)}
              className="color-picker-input"
              style={{ width: 18, height: 18 }}
              title="Custom color"
            />
          </div>
        )}
      </div>

      {/* Deactivate / cursor mode */}
      {activeTool !== null && (
        <button
          title="Cancel drawing — back to pointer"
          onClick={() => onToolSelect(null)}
          className="cursor-pointer rounded transition-all duration-100"
          style={{
            width: 28,
            height: 28,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "transparent",
            color: "var(--color-ink-muted)",
            border: "1px solid transparent",
            fontSize: 14,
            lineHeight: 1,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor =
              "var(--color-line)";
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-ink)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor =
              "transparent";
            (e.currentTarget as HTMLButtonElement).style.color =
              "var(--color-ink-muted)";
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
}
