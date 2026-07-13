"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  approveStrategyDraft,
  generateStrategyCode,
  getStrategyDraft,
  getStrategyVersions,
  rejectStrategyDraft,
  updateStrategyDraftSpec,
  type ExtractedStrategySpec,
  type GeneratedCode,
  type IndicatorSpec,
  type IndicatorType,
  type PriceLevelAnnotation,
  type PriceLevelAnnotationType,
  type StrategyDraft,
} from "@/shared/api/client";
import { RenameVersionInline } from "./RenameVersionInline";
import { StatusBadge } from "./StatusBadge";
import { StrategyVersionList } from "./StrategyVersionList";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

const EDITABLE_STATUSES = new Set(["pending_review", "approved"]);
const INDICATOR_TYPES: IndicatorType[] = ["ema", "sma", "rsi", "macd", "bollinger"];
const PRICE_LEVEL_TYPES: PriceLevelAnnotationType[] = ["support", "resistance", "level"];

interface SpecFormState {
  name: string;
  symbols: string[];
  entry_timeframe: string;
  confirmation_timeframes: string;
  indicators: IndicatorSpec[];
  unrecognized_indicators: string;
  price_levels: PriceLevelAnnotation[];
  chart_notes: string;
  entry_rules: string;
  exit_rules: string;
  risk_notes: string;
  params: string;
}

/** Draft review/edit/approve/generate-code screen (§8.1). Human review is
 * never skippable: editing resets status to pending_review, and "Generate
 * strategy code" only appears once the spec is approved. */
export function StrategyDraftDetail({ draftId }: { draftId: string }) {
  const [draft, setDraft] = useState<StrategyDraft | null>(null);
  const [form, setForm] = useState<SpecFormState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [generated, setGenerated] = useState<GeneratedCode | null>(null);
  // Once code is generated, the "current name" lives on the strategy version
  // record (renamable independently of this draft) rather than the spec —
  // resolved lazily below so the header's rename pencil targets the right id.
  const [latestVersion, setLatestVersion] = useState<{ id: string; name: string } | null>(null);

  useEffect(() => {
    getStrategyDraft(draftId)
      .then((d) => {
        setDraft(d);
        setForm(toFormState(d.effective_spec));
      })
      .catch(() => setError("draft not found"));
  }, [draftId]);

  useEffect(() => {
    if (draft?.status !== "code_generated") return;
    getStrategyVersions(draft.effective_spec.name)
      .then((versions) => {
        if (versions.length > 0) setLatestVersion({ id: versions[0].id, name: versions[0].name });
      })
      .catch(() => {});
  }, [draft?.status, draft?.effective_spec.name]);

  if (error && draft === null) return <p className="p-4 text-sm text-err">{error}</p>;
  if (draft === null || form === null) {
    return <p className="p-4 text-sm text-ink-muted">Loading…</p>;
  }

  const editable = EDITABLE_STATUSES.has(draft.status);

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "action failed");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    const spec = fromFormState(form!);
    if (spec === null) {
      setError("params must be valid JSON");
      return;
    }
    const updated = await run(() => updateStrategyDraftSpec(draftId, spec));
    if (updated) {
      setDraft(updated);
      setForm(toFormState(updated.effective_spec));
    }
  }

  async function onApprove() {
    const updated = await run(() => approveStrategyDraft(draftId));
    if (updated) setDraft(updated);
  }

  async function onReject() {
    const updated = await run(() => rejectStrategyDraft(draftId));
    if (updated) setDraft(updated);
  }

  async function onGenerate() {
    const result = await run(() => generateStrategyCode(draftId));
    if (result) {
      setGenerated(result);
      const updated = await getStrategyDraft(draftId);
      setDraft(updated);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <Link href="/bots" className="text-xs text-ink-muted hover:text-accent">
          ← All bots
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold">{latestVersion?.name ?? draft.effective_spec.name}</h2>
          {latestVersion && (
            <RenameVersionInline
              versionId={latestVersion.id}
              name={latestVersion.name}
              onRenamed={(newName) => setLatestVersion({ ...latestVersion, name: newName })}
            />
          )}
          <StatusBadge status={draft.status} />
        </div>
        <p className="text-sm text-ink-muted">from {draft.source_filename}</p>
      </div>

      <section className="flex flex-col gap-3 rounded-md border border-line bg-panel p-3 text-sm">
        <Field label="Name">
          <input
            className={inputCls}
            value={form.name}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Symbols">
            <SymbolMultiSelect
              value={form.symbols}
              onChange={(symbols) => setForm({ ...form, symbols })}
              disabled={!editable}
            />
            <p className="text-xs text-ink-muted">
              Independent from configs/app.yaml — generating a bot for a new symbol doesn&apos;t
              make the engine trade it live; adding it there is a separate, human-confirmed step.
            </p>
          </Field>
          <Field label="Confirmation timeframes (comma-separated)">
            <input
              className={inputCls}
              value={form.confirmation_timeframes}
              disabled={!editable}
              onChange={(e) => setForm({ ...form, confirmation_timeframes: e.target.value })}
            />
          </Field>
        </div>
        <Field label="Entry timeframe">
          <input
            className={inputCls}
            value={form.entry_timeframe}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, entry_timeframe: e.target.value })}
          />
        </Field>
        <Field label="Indicators (plottable on the chart)">
          <IndicatorListEditor
            value={form.indicators}
            onChange={(indicators) => setForm({ ...form, indicators })}
            disabled={!editable}
          />
        </Field>
        <Field label="Other indicators mentioned (comma-separated, not charted)">
          <input
            className={inputCls}
            value={form.unrecognized_indicators}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, unrecognized_indicators: e.target.value })}
          />
        </Field>
        <Field label="Price levels (rendered as locked horizontal lines)">
          <PriceLevelListEditor
            value={form.price_levels}
            onChange={(price_levels) => setForm({ ...form, price_levels })}
            disabled={!editable}
          />
        </Field>
        <Field label="Chart notes (comma-separated, no explicit price — informational only)">
          <input
            className={inputCls}
            value={form.chart_notes}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, chart_notes: e.target.value })}
          />
        </Field>
        <Field label="Entry rules">
          <textarea
            className={`${inputCls} min-h-20`}
            value={form.entry_rules}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, entry_rules: e.target.value })}
          />
        </Field>
        <Field label="Exit rules">
          <textarea
            className={`${inputCls} min-h-20`}
            value={form.exit_rules}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, exit_rules: e.target.value })}
          />
        </Field>
        <Field label="Risk notes (informational only — real caps live in configs/risk.yaml)">
          <textarea
            className={`${inputCls} min-h-16`}
            value={form.risk_notes}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, risk_notes: e.target.value })}
          />
        </Field>
        <Field label="Params (JSON)">
          <textarea
            className={`${inputCls} min-h-16 font-mono text-xs`}
            value={form.params}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, params: e.target.value })}
          />
        </Field>

        {editable && (
          <div className="flex flex-wrap gap-2 pt-1">
            <button className={btnCls} disabled={busy} onClick={onSave} type="button">
              Save edits
            </button>
            {draft.status === "pending_review" && (
              <button className={btnAccentCls} disabled={busy} onClick={onApprove} type="button">
                Approve
              </button>
            )}
            <button className={btnErrCls} disabled={busy} onClick={onReject} type="button">
              Reject
            </button>
            {draft.status === "approved" && (
              <button className={btnAccentCls} disabled={busy} onClick={onGenerate} type="button">
                {busy ? "Generating…" : "Generate strategy code"}
              </button>
            )}
          </div>
        )}

        {error && <p className="text-err">{error}</p>}
      </section>

      {generated && (
        <section className="rounded-md border border-line bg-panel p-3 text-sm">
          <header className="mb-2 flex items-center gap-2">
            <strong>Generated code</strong>
            {generated.is_valid ? (
              <span className="text-ok">passed sandbox validation</span>
            ) : (
              <span className="text-err">rejected by sandbox</span>
            )}
          </header>
          {!generated.is_valid && (
            <ul className="mb-2 list-inside list-disc text-err">
              {generated.sandbox_errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
          <pre className="max-h-80 overflow-auto rounded bg-bg p-2 text-xs">{generated.code}</pre>
          {generated.version_id && (
            <p className="mt-2">
              <Link
                href={`/strategies/versions/${generated.version_id}`}
                className="text-accent hover:underline"
              >
                View version →
              </Link>
              {generated.backtest_report_id && (
                <>
                  {" · "}
                  <Link
                    href={`/backtest/${generated.backtest_report_id}`}
                    className="text-accent hover:underline"
                  >
                    Backtest report →
                  </Link>
                </>
              )}
            </p>
          )}
        </section>
      )}

      {draft.status === "code_generated" && (
        <section className="rounded-md border border-line bg-panel">
          <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
            Versions of {draft.effective_spec.name}
          </header>
          <StrategyVersionList name={draft.effective_spec.name} />
        </section>
      )}
    </div>
  );
}

function toFormState(spec: ExtractedStrategySpec): SpecFormState {
  return {
    name: spec.name,
    symbols: spec.symbols,
    entry_timeframe: spec.entry_timeframe,
    confirmation_timeframes: spec.confirmation_timeframes.join(", "),
    indicators: spec.indicators,
    unrecognized_indicators: spec.unrecognized_indicators.join(", "),
    price_levels: spec.price_levels,
    chart_notes: spec.chart_notes.join(", "),
    entry_rules: spec.entry_rules,
    exit_rules: spec.exit_rules,
    risk_notes: spec.risk_notes,
    params: JSON.stringify(spec.params, null, 2),
  };
}

function fromFormState(form: SpecFormState): ExtractedStrategySpec | null {
  let params: Record<string, unknown>;
  try {
    params = JSON.parse(form.params || "{}");
  } catch {
    return null;
  }
  return {
    name: form.name.trim(),
    symbols: form.symbols,
    entry_timeframe: form.entry_timeframe.trim(),
    confirmation_timeframes: splitList(form.confirmation_timeframes),
    indicators: form.indicators,
    unrecognized_indicators: splitList(form.unrecognized_indicators),
    price_levels: form.price_levels,
    chart_notes: splitList(form.chart_notes),
    entry_rules: form.entry_rules,
    exit_rules: form.exit_rules,
    risk_notes: form.risk_notes,
    params,
  };
}

function splitList(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function defaultIndicator(type: IndicatorType): IndicatorSpec {
  const defaults: Record<IndicatorType, { period: number; params: Record<string, number> }> = {
    ema: { period: 200, params: {} },
    sma: { period: 50, params: {} },
    rsi: { period: 14, params: {} },
    macd: { period: 12, params: { slow: 26, signal: 9 } },
    bollinger: { period: 20, params: { std_dev: 2 } },
  };
  const d = defaults[type];
  return { type, period: d.period, label: type.toUpperCase(), source: "close", params: d.params };
}

/** One row per indicator, each with its family, period, label, and any
 * family-specific params (macd: slow/signal, bollinger: std_dev) edited as
 * raw JSON since the shape differs per family. */
function IndicatorListEditor({
  value,
  onChange,
  disabled,
}: {
  value: IndicatorSpec[];
  onChange: (value: IndicatorSpec[]) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {value.map((indicator, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1">
          <select
            className={inputCls}
            value={indicator.type}
            disabled={disabled}
            onChange={(e) => {
              const updated = [...value];
              updated[i] = defaultIndicator(e.target.value as IndicatorType);
              onChange(updated);
            }}
          >
            {INDICATOR_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            className={`${inputCls} w-20`}
            type="number"
            value={indicator.period}
            disabled={disabled}
            title="Period"
            onChange={(e) => {
              const updated = [...value];
              updated[i] = { ...indicator, period: Number(e.target.value) };
              onChange(updated);
            }}
          />
          <input
            className={`${inputCls} w-28`}
            value={indicator.label}
            disabled={disabled}
            placeholder="Label"
            onChange={(e) => {
              const updated = [...value];
              updated[i] = { ...indicator, label: e.target.value };
              onChange(updated);
            }}
          />
          {(indicator.type === "macd" || indicator.type === "bollinger") && (
            <input
              className={`${inputCls} w-40 font-mono text-xs`}
              value={JSON.stringify(indicator.params)}
              disabled={disabled}
              title="Family-specific params (JSON)"
              onChange={(e) => {
                try {
                  const params = JSON.parse(e.target.value);
                  const updated = [...value];
                  updated[i] = { ...indicator, params };
                  onChange(updated);
                } catch {
                  // Invalid JSON while typing — ignored until it parses.
                }
              }}
            />
          )}
          {!disabled && (
            <button
              type="button"
              className="cursor-pointer text-ink-muted hover:text-err"
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              ×
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button
          type="button"
          className={`${btnCls} w-fit`}
          onClick={() => onChange([...value, defaultIndicator("ema")])}
        >
          + Add indicator
        </button>
      )}
    </div>
  );
}

/** One row per explicit numeric price level (support/resistance/level). */
function PriceLevelListEditor({
  value,
  onChange,
  disabled,
}: {
  value: PriceLevelAnnotation[];
  onChange: (value: PriceLevelAnnotation[]) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {value.map((level, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1">
          <select
            className={inputCls}
            value={level.type}
            disabled={disabled}
            onChange={(e) => {
              const updated = [...value];
              updated[i] = { ...level, type: e.target.value as PriceLevelAnnotationType };
              onChange(updated);
            }}
          >
            {PRICE_LEVEL_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            className={`${inputCls} w-24`}
            type="number"
            value={level.price}
            disabled={disabled}
            title="Price"
            onChange={(e) => {
              const updated = [...value];
              updated[i] = { ...level, price: Number(e.target.value) };
              onChange(updated);
            }}
          />
          <input
            className={`${inputCls} w-40`}
            value={level.label}
            disabled={disabled}
            placeholder="Label"
            onChange={(e) => {
              const updated = [...value];
              updated[i] = { ...level, label: e.target.value };
              onChange(updated);
            }}
          />
          {!disabled && (
            <button
              type="button"
              className="cursor-pointer text-ink-muted hover:text-err"
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              ×
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button
          type="button"
          className={`${btnCls} w-fit`}
          onClick={() =>
            onChange([...value, { type: "resistance", price: 0, label: "" }])
          }
        >
          + Add price level
        </button>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none disabled:opacity-60";
const btnCls =
  "cursor-pointer rounded border border-line px-3 py-1 hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";
const btnAccentCls =
  "cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50";
const btnErrCls =
  "cursor-pointer rounded border border-line px-3 py-1 hover:border-err hover:text-err disabled:cursor-not-allowed disabled:opacity-50";
