"use client";

/**
 * IndicatorsDock — TradingView-style panel for manually adding indicator
 * overlays to the chart, independent of whatever the active strategy's
 * PDF-derived spec already draws (see ChartPanel.tsx's `recomputeIndicators`,
 * which plots strategy + manual indicators together).
 *
 * Rendered inside ChartPanel below the chart header when the user clicks the
 * "Indicators (N)" toggle button, same slot/style as DrawingsList.
 */

import { useState } from "react";
import type { ManualIndicator, ManualIndicatorType } from "./ChartPanel";

const PRESET_COLORS = [
  "#42a5f5", // Blue
  "#ffa726", // Orange
  "#ab47bc", // Purple
  "#26a69a", // Green
  "#ef5350", // Red
  "#78909c", // Grey
];

const TYPE_LABELS: Record<ManualIndicatorType, string> = {
  ema: "EMA",
  sma: "SMA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "Bollinger Bands",
  vwap: "VWAP",
  atr: "ATR",
};

/** Default period per type, and whether the period is even user-editable. */
const TYPE_DEFAULTS: Record<ManualIndicatorType, { period: number; editablePeriod: boolean }> = {
  ema: { period: 20, editablePeriod: true },
  sma: { period: 20, editablePeriod: true },
  rsi: { period: 14, editablePeriod: true },
  atr: { period: 14, editablePeriod: true },
  bollinger: { period: 20, editablePeriod: true },
  macd: { period: 12, editablePeriod: false }, // fixed 12/26/9, see indicatorLabel()
  vwap: { period: 0, editablePeriod: false }, // cumulative, no period
};

/** Builds the display label shown in the chip list and on the chart series. */
function indicatorLabel(type: ManualIndicatorType, period: number): string {
  switch (type) {
    case "macd":
      return "MACD (12/26/9)";
    case "vwap":
      return "VWAP";
    case "bollinger":
      return `Bollinger (${period}, 2σ)`;
    default:
      return `${TYPE_LABELS[type]} (${period})`;
  }
}

interface Props {
  indicators: ManualIndicator[];
  onAdd: (indicator: ManualIndicator) => void;
  onRemove: (id: string) => void;
}

export function IndicatorsDock({ indicators, onAdd, onRemove }: Props) {
  const [type, setType] = useState<ManualIndicatorType>("ema");
  const [period, setPeriod] = useState<number>(TYPE_DEFAULTS.ema.period);
  const [color, setColor] = useState<string>(PRESET_COLORS[0]);

  const defaults = TYPE_DEFAULTS[type];

  function handleTypeChange(next: ManualIndicatorType) {
    setType(next);
    setPeriod(TYPE_DEFAULTS[next].period);
  }

  function handleAdd() {
    const resolvedPeriod = defaults.editablePeriod ? period : defaults.period;
    onAdd({
      id: crypto.randomUUID(),
      type,
      period: resolvedPeriod,
      color,
      label: indicatorLabel(type, resolvedPeriod),
    });
  }

  return (
    <div
      style={{
        borderBottom: "1px solid var(--color-line)",
        background: "var(--color-panel)",
      }}
    >
      {/* Add-indicator form */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          borderBottom: indicators.length > 0 ? "1px solid var(--color-line)" : "none",
        }}
      >
        <select
          value={type}
          onChange={(e) => handleTypeChange(e.target.value as ManualIndicatorType)}
          className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
        >
          {(Object.keys(TYPE_LABELS) as ManualIndicatorType[]).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>

        {defaults.editablePeriod && (
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--color-ink-muted)" }}>
            Period
            <input
              type="number"
              min={1}
              max={500}
              value={period}
              onChange={(e) => setPeriod(Math.max(1, Number(e.target.value) || 1))}
              className="rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
              style={{ width: 56 }}
            />
          </label>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          {PRESET_COLORS.map((c) => (
            <button
              key={c}
              title={c}
              onClick={() => setColor(c)}
              className="cursor-pointer rounded-full transition-transform hover:scale-110"
              style={{
                width: 14,
                height: 14,
                backgroundColor: c,
                border: color === c ? "2px solid var(--color-ink)" : "1px solid var(--color-line)",
              }}
            />
          ))}
          <input
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="color-picker-input"
            style={{ width: 14, height: 14 }}
            title="Custom color"
          />
        </div>

        <button
          onClick={handleAdd}
          className="cursor-pointer rounded border border-accent px-2 py-0.5 text-xs text-accent"
        >
          + Add
        </button>
      </div>

      {/* Active manual indicators */}
      {indicators.length === 0 ? (
        <div style={{ padding: "8px 16px", fontSize: 12, color: "var(--color-ink-muted)" }}>
          No manual indicators yet. Pick a type above and click Add.
        </div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "6px 12px" }}>
          {indicators.map((ind) => (
            <span
              key={ind.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                borderRadius: 4,
                border: "1px solid var(--color-line)",
                padding: "2px 6px",
                fontSize: 12,
                color: "var(--color-ink)",
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: ind.color,
                  flexShrink: 0,
                }}
              />
              {ind.label}
              <button
                title="Remove this indicator"
                onClick={() => onRemove(ind.id)}
                style={{
                  background: "transparent",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--color-err)",
                  fontSize: 11,
                  padding: 0,
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
