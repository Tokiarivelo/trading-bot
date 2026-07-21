"use client";

/**
 * IndicatorsDock — TradingView-style panel for manually adding indicator
 * overlays to the chart, independent of whatever the active strategy's
 * PDF-derived spec already draws (see ChartPanel.tsx's `recomputeIndicators`,
 * which plots strategy + manual indicators together).
 *
 * Rendered inside ChartPanel below the chart header when the user clicks the
 * "Indicators (N)" toggle button, same slot/style as DrawingsList.
 *
 * The "custom" indicator type doubles as an ad-hoc code workbench: besides
 * picking a saved indicator (with View/Run shortcuts right on the picker),
 * "Write new code…" opens an inline CodeMirror editor to run unsaved code
 * against the live chart and, once happy with it, save it as a normal
 * reusable saved indicator (POST /indicators) — bridging the old separate
 * "Run Custom Code" script drawer and the /indicators CRUD system.
 */

import { python } from '@codemirror/lang-python';
import { githubDarkInit } from '@uiw/codemirror-theme-github';
import CodeMirror from '@uiw/react-codemirror';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  ApiError,
  createIndicator,
  listIndicators,
  type IndicatorSummary,
} from '@/shared/api/client';
import type { ManualIndicator, ManualIndicatorType } from './ChartPanel';
import { IndicatorCodePeek } from './IndicatorCodePeek';

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
  snd: "S&D zones (RBR/DBD/RBD/DBR)",
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
  // period here is the max base-candle count of a zone, same meaning as
  // maxBaseCandles in sndZones() (indicators.ts).
  snd: { period: 3, editablePeriod: true },
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
    case "snd":
      return `S&D zones (base ≤ ${period})`;
    case "patterns":
      return "Candlestick patterns";
    default:
      return `${TYPE_LABELS[type]} (${period})`;
  }
}

const cmTheme = githubDarkInit({
  settings: {
    background: 'var(--color-bg)',
    gutterBackground: 'var(--color-bg)',
    lineHighlight: 'var(--color-panel)',
    foreground: 'var(--color-ink)',
    caret: 'var(--color-accent)',
    selection: 'color-mix(in srgb, var(--color-accent) 30%, transparent)',
  },
});

/** Sentinel `<option>` value that switches the custom-indicator picker into
 * "write ad-hoc code" mode instead of selecting a saved indicator. */
const NEW_CODE_OPTION = '__new__';

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

  // Ad-hoc "write new code" workbench state — a single unsaved preview chip
  // (stable id below) drawn via ManualIndicator.previewCode instead of a
  // saved indicatorId, computed by ChartPanel's existing custom-indicator
  // compute effect through POST /indicators/preview.
  const [previewChipId] = useState(() => `preview-${crypto.randomUUID()}`);
  const [newCode, setNewCode] = useState('');
  const [newCodeRan, setNewCodeRan] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  function refreshCustomIndicators() {
    return listIndicators()
      .then(setCustomIndicators)
      .catch(() => setCustomIndicators([]));
  }

  useEffect(() => {
    refreshCustomIndicators();
  }, []);

  const defaults = TYPE_DEFAULTS[type];
  const writingNewCode = type === 'custom' && selectedCustomId === NEW_CODE_OPTION;

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

  function handleViewSelectedCode() {
    const chosen = customIndicators.find((c) => c.id === selectedCustomId);
    if (chosen) setPeekIndicator({ id: chosen.id, name: chosen.name });
  }

  function handleRunPreview() {
    if (!newCode.trim()) return;
    onRemove(previewChipId);
    onAdd({
      id: previewChipId,
      type: 'custom',
      period: 0,
      color,
      label: 'Preview (unsaved)',
      previewCode: newCode,
    });
    setNewCodeRan(true);
    setSaveError(null);
  }

  async function handleSaveAsIndicator() {
    if (!saveName.trim()) return;
    setSaveBusy(true);
    setSaveError(null);
    try {
      const created = await createIndicator({ name: saveName.trim(), code: newCode });
      await refreshCustomIndicators();
      onRemove(previewChipId);
      onAdd({
        id: crypto.randomUUID(),
        type: 'custom',
        period: 0,
        color,
        label: created.name,
        indicatorId: created.id,
      });
      setSelectedCustomId(created.id);
      setNewCode('');
      setNewCodeRan(false);
      setSaveName('');
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : 'save failed');
    } finally {
      setSaveBusy(false);
    }
  }

  function handleCancelNewCode() {
    if (newCodeRan) onRemove(previewChipId);
    setNewCode('');
    setNewCodeRan(false);
    setSaveName('');
    setSaveError(null);
    setSelectedCustomId(customIndicators[0]?.id ?? null);
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
          borderBottom: indicators.length > 0 || writingNewCode ? "1px solid var(--color-line)" : "none",
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
          <>
            <select
              value={selectedCustomId ?? ""}
              onChange={(e) => setSelectedCustomId(e.target.value || null)}
              className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
            >
              <option value={NEW_CODE_OPTION}>✏️ Write new code…</option>
              {customIndicators.length === 0 && <option value="">No saved indicators yet</option>}
              {customIndicators.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {!writingNewCode && (
              <>
                <button
                  type="button"
                  title="View this indicator's code"
                  onClick={handleViewSelectedCode}
                  disabled={!selectedCustomId}
                  className="cursor-pointer rounded border border-line px-1.5 py-0.5 text-xs text-ink-muted hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  👁 View code
                </button>
                <button
                  type="button"
                  title="Run this indicator now and draw it on the chart"
                  onClick={handleAdd}
                  disabled={!selectedCustomId}
                  className="cursor-pointer rounded border border-accent px-1.5 py-0.5 text-xs text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  ▶ Run
                </button>
              </>
            )}
          </>
        )}

        {defaults.editablePeriod && type !== 'custom' && (
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

        {!writingNewCode && (
          <button
            onClick={handleAdd}
            disabled={type === "custom" && !selectedCustomId}
            className="cursor-pointer rounded border border-accent px-2 py-0.5 text-xs text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            + Add
          </button>
        )}

        <Link
          href="/indicators"
          className="ml-auto text-xs text-ink-muted hover:text-accent"
        >
          Manage indicators →
        </Link>
      </div>

      {/* Ad-hoc "write new code" workbench */}
      {writingNewCode && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: "8px 12px",
            borderBottom: indicators.length > 0 ? "1px solid var(--color-line)" : "none",
          }}
        >
          <div className="overflow-hidden rounded border border-line">
            <CodeMirror
              value={newCode}
              height="10rem"
              theme={cmTheme}
              extensions={[python()]}
              onChange={setNewCode}
              placeholder={
                'class MyIndicator:\n    def compute(self, candles, params):\n        return {"value": [...]}'
              }
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              onClick={handleRunPreview}
              disabled={!newCode.trim()}
              className="cursor-pointer rounded border border-accent px-2 py-0.5 text-xs text-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              ▶ Run & Draw
            </button>
            {newCodeRan && (
              <>
                <input
                  type="text"
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Name to save as…"
                  className="rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
                  style={{ width: 160 }}
                />
                <button
                  type="button"
                  onClick={handleSaveAsIndicator}
                  disabled={saveBusy || !saveName.trim()}
                  className="cursor-pointer rounded border border-ok px-2 py-0.5 text-xs text-ok disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saveBusy ? "Saving…" : "💾 Save as indicator"}
                </button>
              </>
            )}
            <button
              type="button"
              onClick={handleCancelNewCode}
              className="cursor-pointer rounded border border-line px-2 py-0.5 text-xs text-ink-muted hover:border-err hover:text-err"
            >
              Cancel
            </button>
          </div>
          {saveError && <p style={{ fontSize: 11, color: "var(--color-err)" }}>{saveError}</p>}
          {!newCodeRan && (
            <p style={{ fontSize: 11, color: "var(--color-ink-muted)" }}>
              Define a class with a <code>compute(candles, params)</code> method returning a dict
              of named series. Run it to preview on the chart before saving.
            </p>
          )}
        </div>
      )}

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
