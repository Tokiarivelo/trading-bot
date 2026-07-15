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

import Link from "next/link";
import { useEffect, useState } from "react";
import { listIndicators, type IndicatorSummary } from "@/shared/api/client";
import type { ManualIndicator, ManualIndicatorType } from "./ChartPanel";
import { IndicatorCodePeek } from "./IndicatorCodePeek";

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
  structure: "Structure (HH/HL/LH/LL)",
  qml: "Quasimodo (QML / inversed)",
  patterns: "Candlestick patterns",
  custom: "Custom (saved indicator)",
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
  // period here is the swing-detection lookback (bars each side), same
  // meaning as the backend vix75 strategy's `swing_lookback` param.
  structure: { period: 3, editablePeriod: true },
  qml: { period: 3, editablePeriod: true },
  patterns: { period: 0, editablePeriod: false }, // fixed thresholds, no period
  // Params come from the saved indicator's own default_params (edit them on
  // /indicators, or from the code-peek panel below) rather than this dock.
  custom: { period: 0, editablePeriod: false },
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
    case "structure":
      return `Structure (lookback ${period})`;
    case "qml":
      return `Quasimodo (lookback ${period})`;
    case "patterns":
      return "Candlestick patterns";
    default:
      return `${TYPE_LABELS[type]} (${period})`;
  }
}

interface Props {
  indicators: ManualIndicator[];
  onAdd: (indicator: ManualIndicator) => void;
  onRemove: (id: string) => void;
  /** Called after the code-peek panel saves an edit to a saved indicator's
   * code, so the chart can recompute every chip currently using it. */
  onCustomIndicatorCodeSaved: () => void;
}

export function IndicatorsDock({ indicators, onAdd, onRemove, onCustomIndicatorCodeSaved }: Props) {
  const [type, setType] = useState<ManualIndicatorType>("ema");
  const [period, setPeriod] = useState<number>(TYPE_DEFAULTS.ema.period);
  const [color, setColor] = useState<string>(PRESET_COLORS[0]);
  const [customIndicators, setCustomIndicators] = useState<IndicatorSummary[]>([]);
  const [selectedCustomId, setSelectedCustomId] = useState<string | null>(null);
  const [peekIndicator, setPeekIndicator] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    listIndicators()
      .then(setCustomIndicators)
      .catch(() => setCustomIndicators([]));
  }, []);

  const defaults = TYPE_DEFAULTS[type];

  function handleTypeChange(next: ManualIndicatorType) {
    setType(next);
    setPeriod(TYPE_DEFAULTS[next].period);
    if (next === "custom") setSelectedCustomId(customIndicators[0]?.id ?? null);
  }

  function handleAdd() {
    if (type === "custom") {
      const chosen = customIndicators.find((c) => c.id === selectedCustomId);
      if (!chosen) return;
      onAdd({
        id: crypto.randomUUID(),
        type,
        period: 0,
        color,
        label: chosen.name,
        indicatorId: chosen.id,
      });
      return;
    }
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

        {type === "custom" && (
          <select
            value={selectedCustomId ?? ""}
            onChange={(e) => setSelectedCustomId(e.target.value || null)}
            className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
          >
            {customIndicators.length === 0 && <option value="">No saved indicators yet</option>}
            {customIndicators.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}

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
          disabled={type === "custom" && !selectedCustomId}
          className="cursor-pointer rounded border border-accent px-2 py-0.5 text-xs text-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          + Add
        </button>

        <Link
          href="/indicators"
          className="ml-auto text-xs text-ink-muted hover:text-accent"
        >
          Manage indicators →
        </Link>
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
              {ind.type === "custom" && ind.indicatorId && (
                <button
                  title="View/edit this indicator's code"
                  onClick={() =>
                    setPeekIndicator({ id: ind.indicatorId as string, name: ind.label })
                  }
                  style={{
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--color-ink-muted)",
                    fontSize: 11,
                    padding: 0,
                    lineHeight: 1,
                  }}
                >
                  ✏️
                </button>
              )}
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

      {peekIndicator && (
        <IndicatorCodePeek
          indicatorId={peekIndicator.id}
          indicatorName={peekIndicator.name}
          onClose={() => setPeekIndicator(null)}
          onSaved={onCustomIndicatorCodeSaved}
        />
      )}
    </div>
  );
}
