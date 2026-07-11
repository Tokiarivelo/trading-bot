"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  approveStrategyDraft,
  generateStrategyCode,
  getStrategyDraft,
  rejectStrategyDraft,
  updateStrategyDraftSpec,
  type ExtractedStrategySpec,
  type GeneratedCode,
  type StrategyDraft,
} from "@/shared/api/client";
import { StatusBadge } from "./StatusBadge";
import { StrategyVersionList } from "./StrategyVersionList";

const EDITABLE_STATUSES = new Set(["pending_review", "approved"]);

interface SpecFormState {
  name: string;
  symbols: string;
  entry_timeframe: string;
  confirmation_timeframes: string;
  indicators: string;
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

  useEffect(() => {
    getStrategyDraft(draftId)
      .then((d) => {
        setDraft(d);
        setForm(toFormState(d.effective_spec));
      })
      .catch(() => setError("draft not found"));
  }, [draftId]);

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
        <Link href="/strategies" className="text-xs text-ink-muted hover:text-accent">
          ← All strategies
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold">{draft.effective_spec.name}</h2>
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
          <Field label="Symbols (comma-separated)">
            <input
              className={inputCls}
              value={form.symbols}
              disabled={!editable}
              onChange={(e) => setForm({ ...form, symbols: e.target.value })}
            />
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
        <Field label="Indicators (comma-separated)">
          <input
            className={inputCls}
            value={form.indicators}
            disabled={!editable}
            onChange={(e) => setForm({ ...form, indicators: e.target.value })}
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
    symbols: spec.symbols.join(", "),
    entry_timeframe: spec.entry_timeframe,
    confirmation_timeframes: spec.confirmation_timeframes.join(", "),
    indicators: spec.indicators.join(", "),
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
    symbols: splitList(form.symbols),
    entry_timeframe: form.entry_timeframe.trim(),
    confirmation_timeframes: splitList(form.confirmation_timeframes),
    indicators: splitList(form.indicators),
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
