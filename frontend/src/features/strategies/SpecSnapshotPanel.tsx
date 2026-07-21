"use client";

/** Spec snapshot for a strategy version (§6.5): read-only by default, with
 * an "Edit" mode that hand-edits every field and saves in place via
 * PATCH .../spec. Annotation only — unlike the code editor, saving never
 * touches the generated Python or creates a new version. */

import { useState } from "react";
import {
  ApiError,
  updateStrategyVersionSpec,
  type ExtractedStrategySpec,
  type IndicatorSpec,
  type PriceLevelAnnotation,
} from "@/shared/api/client";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

interface SpecFormState {
  name: string;
  symbols: string[];
  entryTimeframe: string;
  confirmationTimeframes: string; // comma-separated
  entryRules: string;
  exitRules: string;
  riskNotes: string;
  paramsJson: string;
  indicatorsJson: string;
  unrecognizedIndicators: string; // one per line
  priceLevelsJson: string;
  chartNotes: string; // one per line
}

function toFormState(spec: ExtractedStrategySpec): SpecFormState {
  return {
    name: spec.name,
    symbols: spec.symbols,
    entryTimeframe: spec.entry_timeframe,
    confirmationTimeframes: spec.confirmation_timeframes.join(", "),
    entryRules: spec.entry_rules,
    exitRules: spec.exit_rules,
    riskNotes: spec.risk_notes,
    paramsJson: JSON.stringify(spec.params, null, 2),
    indicatorsJson: JSON.stringify(spec.indicators, null, 2),
    unrecognizedIndicators: spec.unrecognized_indicators.join("\n"),
    priceLevelsJson: JSON.stringify(spec.price_levels, null, 2),
    chartNotes: spec.chart_notes.join("\n"),
  };
}

function linesOf(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function buildSpec(form: SpecFormState): ExtractedStrategySpec {
  let params: Record<string, unknown>;
  let indicators: IndicatorSpec[];
  let priceLevels: PriceLevelAnnotation[];
  try {
    params = JSON.parse(form.paramsJson || "{}");
  } catch {
    throw new Error("params must be valid JSON");
  }
  try {
    indicators = JSON.parse(form.indicatorsJson || "[]");
  } catch {
    throw new Error("indicators must be valid JSON");
  }
  try {
    priceLevels = JSON.parse(form.priceLevelsJson || "[]");
  } catch {
    throw new Error("price levels must be valid JSON");
  }
  return {
    name: form.name.trim(),
    symbols: form.symbols,
    entry_timeframe: form.entryTimeframe.trim(),
    confirmation_timeframes: form.confirmationTimeframes
      .split(",")
      .map((tf) => tf.trim())
      .filter(Boolean),
    indicators,
    entry_rules: form.entryRules,
    exit_rules: form.exitRules,
    risk_notes: form.riskNotes,
    params,
    unrecognized_indicators: linesOf(form.unrecognizedIndicators),
    price_levels: priceLevels,
    chart_notes: linesOf(form.chartNotes),
  };
}

export function SpecSnapshotPanel({
  versionId,
  spec,
  onSaved,
}: {
  versionId: string;
  spec: ExtractedStrategySpec;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<SpecFormState>(() => toFormState(spec));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit() {
    setForm(toFormState(spec));
    setError(null);
    setEditing(true);
  }

  function cancel() {
    setError(null);
    setEditing(false);
  }

  async function save() {
    let payload: ExtractedStrategySpec;
    try {
      payload = buildSpec(form);
    } catch (e) {
      setError(e instanceof Error ? e.message : "invalid spec");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateStrategyVersionSpec(versionId, payload);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-md border border-line bg-panel p-3 text-sm">
      <header className="mb-2 flex items-center justify-between text-ink-muted">
        <span>Spec snapshot</span>
        {editing ? (
          <div className="flex gap-2">
            <button type="button" className={btnCls} disabled={busy} onClick={cancel}>
              Cancel
            </button>
            <button type="button" className={btnAccentCls} disabled={busy} onClick={save}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        ) : (
          <button type="button" className={btnCls} onClick={startEdit}>
            Edit
          </button>
        )}
      </header>

      {error && <p className="mb-2 text-xs text-err">{error}</p>}

      {!editing ? (
        <>
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            <Row label="Name" value={spec.name} />
            <Row label="Symbols" value={spec.symbols.join(", ")} />
            <Row label="Entry timeframe" value={spec.entry_timeframe} />
            <Row
              label="Confirmation timeframes"
              value={spec.confirmation_timeframes.join(", ")}
            />
            <Row label="Indicators" value={spec.indicators.map((i) => i.label).join(", ") || "—"} />
            {spec.unrecognized_indicators.length > 0 && (
              <Row
                label="Other indicators (not charted)"
                value={spec.unrecognized_indicators.join(", ")}
              />
            )}
            {spec.price_levels.length > 0 && (
              <Row
                label="Price levels"
                value={spec.price_levels.map((l) => `${l.type} @ ${l.price}`).join(", ")}
              />
            )}
            {spec.chart_notes.length > 0 && (
              <Row label="Chart notes" value={spec.chart_notes.join(", ")} />
            )}
            {Object.keys(spec.params).length > 0 && (
              <Row label="Params" value={JSON.stringify(spec.params)} />
            )}
          </dl>
          <p className="mt-2 whitespace-pre-wrap text-ink-muted">
            <strong className="text-ink">Entry:</strong> {spec.entry_rules}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-ink-muted">
            <strong className="text-ink">Exit:</strong> {spec.exit_rules}
          </p>
        </>
      ) : (
        <div className="flex flex-col gap-2 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Name</span>
            <input
              className={inputCls}
              value={form.name}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, name: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Symbols</span>
            <SymbolMultiSelect
              value={form.symbols}
              onChange={(symbols) => setForm((s) => ({ ...s, symbols }))}
              disabled={busy}
            />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-ink-muted">Entry timeframe</span>
              <input
                className={inputCls}
                value={form.entryTimeframe}
                disabled={busy}
                onChange={(e) => setForm((s) => ({ ...s, entryTimeframe: e.target.value }))}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-ink-muted">Confirmation timeframes (comma-separated)</span>
              <input
                className={inputCls}
                value={form.confirmationTimeframes}
                disabled={busy}
                onChange={(e) =>
                  setForm((s) => ({ ...s, confirmationTimeframes: e.target.value }))
                }
              />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Entry rules</span>
            <textarea
              className={`${inputCls} min-h-16 resize-y`}
              value={form.entryRules}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, entryRules: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Exit rules</span>
            <textarea
              className={`${inputCls} min-h-16 resize-y`}
              value={form.exitRules}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, exitRules: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">
              Risk notes (informational only — real caps live in configs/risk.yaml)
            </span>
            <textarea
              className={`${inputCls} min-h-12 resize-y`}
              value={form.riskNotes}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, riskNotes: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Params (JSON)</span>
            <textarea
              className={`${inputCls} min-h-16 resize-y font-mono`}
              value={form.paramsJson}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, paramsJson: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">
              Indicators (JSON — type/period/label/source/params each)
            </span>
            <textarea
              className={`${inputCls} min-h-20 resize-y font-mono`}
              value={form.indicatorsJson}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, indicatorsJson: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Other indicators, not charted (one per line)</span>
            <textarea
              className={`${inputCls} min-h-12 resize-y`}
              value={form.unrecognizedIndicators}
              disabled={busy}
              onChange={(e) =>
                setForm((s) => ({ ...s, unrecognizedIndicators: e.target.value }))
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Price levels (JSON — type/price/label each)</span>
            <textarea
              className={`${inputCls} min-h-16 resize-y font-mono`}
              value={form.priceLevelsJson}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, priceLevelsJson: e.target.value }))}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-ink-muted">Chart notes (one per line)</span>
            <textarea
              className={`${inputCls} min-h-12 resize-y`}
              value={form.chartNotes}
              disabled={busy}
              onChange={(e) => setForm((s) => ({ ...s, chartNotes: e.target.value }))}
            />
          </label>
        </div>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2 sm:block">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";
const btnCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";
const btnAccentCls =
  "cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50";
