"use client";

/** Source code panel for a strategy version (§6.5): read-only by default,
 * with two ways to produce a new version — hand-editing the code directly
 * ("Edit"), or describing a change in plain English for the AI to apply
 * ("Regenerate with AI"), optionally against an edited spec snapshot rather
 * than the one it was extracted/saved with. Either flow saves to a save
 * destination the trader picks: "new version" increments this version's
 * own family (the default, recommended choice), "new strategy" forks into
 * a brand-new family at version 1 — same fork semantics as the Duplicate
 * button, just with edited/regenerated code instead of a verbatim copy.
 * Nothing here ever activates a version or edits this one's file in place
 * (versions are immutable). A regeneration that fails sandbox validation
 * drops its proposed code straight into the manual editor so the trader
 * can hand-fix it instead of starting over. */

import { python } from "@codemirror/lang-python";
import { githubDarkInit } from "@uiw/codemirror-theme-github";
import CodeMirror from "@uiw/react-codemirror";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  editStrategyVersionCode,
  regenerateStrategyVersionCode,
  type ExtractedStrategySpec,
} from "@/shared/api/client";
import { SymbolMultiSelect } from "./SymbolMultiSelect";

const cmTheme = githubDarkInit({
  settings: {
    background: "var(--color-bg)",
    gutterBackground: "var(--color-bg)",
    lineHighlight: "var(--color-panel)",
    foreground: "var(--color-ink)",
    caret: "var(--color-accent)",
    selection: "color-mix(in srgb, var(--color-accent) 30%, transparent)",
  },
});

type Mode = "view" | "edit" | "regenerate";
type SaveTarget = "increment" | "duplicate";

interface SpecFormState {
  symbols: string[];
  entryTimeframe: string;
  confirmationTimeframes: string; // comma-separated for editing, split on submit
  entryRules: string;
  exitRules: string;
  riskNotes: string;
  paramsJson: string;
}

function toFormState(spec: ExtractedStrategySpec | null): SpecFormState {
  return {
    symbols: spec?.symbols ?? [],
    entryTimeframe: spec?.entry_timeframe ?? "",
    confirmationTimeframes: spec?.confirmation_timeframes.join(", ") ?? "",
    entryRules: spec?.entry_rules ?? "",
    exitRules: spec?.exit_rules ?? "",
    riskNotes: spec?.risk_notes ?? "",
    paramsJson: JSON.stringify(spec?.params ?? {}, null, 2),
  };
}

export function CodeEditorPanel({
  versionId,
  name,
  code,
  spec,
}: {
  versionId: string;
  name: string;
  code: string;
  spec: ExtractedStrategySpec | null;
}) {
  const router = useRouter();
  const accountId = useActiveAccount();
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState(code);
  const [instructions, setInstructions] = useState("");
  const [specOpen, setSpecOpen] = useState(false);
  const [specDraft, setSpecDraft] = useState<SpecFormState>(() => toFormState(spec));
  const [saveTarget, setSaveTarget] = useState<SaveTarget>("increment");
  const [duplicateName, setDuplicateName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sandboxErrors, setSandboxErrors] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const textToCopy = mode === "edit" ? draft : code;
    navigator.clipboard.writeText(textToCopy);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  function resetSaveDestination() {
    setSaveTarget("increment");
    setDuplicateName("");
  }

  function startEdit() {
    setDraft(code);
    setError(null);
    setSandboxErrors([]);
    resetSaveDestination();
    setMode("edit");
  }

  function startRegenerate() {
    setInstructions("");
    setSpecOpen(false);
    setSpecDraft(toFormState(spec));
    setError(null);
    setSandboxErrors([]);
    resetSaveDestination();
    setMode("regenerate");
  }

  function cancel() {
    setDraft(code);
    setError(null);
    setSandboxErrors([]);
    resetSaveDestination();
    setMode("view");
  }

  function resolveNewName(): string | undefined {
    return saveTarget === "duplicate" ? duplicateName.trim() : undefined;
  }

  function buildSpecOverride(): ExtractedStrategySpec | undefined {
    if (!spec || !specOpen) return undefined;
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(specDraft.paramsJson || "{}");
    } catch {
      throw new Error("params must be valid JSON");
    }
    return {
      ...spec,
      symbols: specDraft.symbols,
      entry_timeframe: specDraft.entryTimeframe,
      confirmation_timeframes: specDraft.confirmationTimeframes
        .split(",")
        .map((tf) => tf.trim())
        .filter(Boolean),
      entry_rules: specDraft.entryRules,
      exit_rules: specDraft.exitRules,
      risk_notes: specDraft.riskNotes,
      params,
    };
  }

  async function onSaveEdit() {
    if (saveTarget === "duplicate" && !duplicateName.trim()) {
      setError("enter a name for the new strategy");
      return;
    }
    if (!accountId) return;
    setBusy(true);
    setError(null);
    setSandboxErrors([]);
    try {
      const saved = await editStrategyVersionCode(accountId, versionId, draft, resolveNewName());
      router.push(`/strategies/versions/${saved.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRegenerate() {
    const trimmed = instructions.trim();
    if (!trimmed) {
      setError("describe what to change first");
      return;
    }
    if (saveTarget === "duplicate" && !duplicateName.trim()) {
      setError("enter a name for the new strategy");
      return;
    }
    let specOverride: ExtractedStrategySpec | undefined;
    try {
      specOverride = buildSpecOverride();
    } catch (e) {
      setError(e instanceof Error ? e.message : "invalid spec");
      return;
    }
    if (!accountId) return;
    setBusy(true);
    setError(null);
    setSandboxErrors([]);
    try {
      const result = await regenerateStrategyVersionCode(
        accountId,
        versionId,
        trimmed,
        specOverride,
        resolveNewName(),
      );
      if (result.new_version_id) {
        router.push(`/strategies/versions/${result.new_version_id}`);
        return;
      }
      // Sandbox rejected the AI's proposal — hand the code to the manual
      // editor instead of discarding it, so the trader can fix it up
      // rather than re-describing the change from scratch. Keep whatever
      // save destination was already chosen.
      setSandboxErrors(result.sandbox_errors);
      setDraft(result.code);
      setMode("edit");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "regeneration failed");
    } finally {
      setBusy(false);
    }
  }

  function saveDestinationFields() {
    return (
      <div className="flex flex-col gap-1.5 text-xs">
        <span className="font-medium text-ink">Save as</span>
        <label className="flex items-center gap-2 text-ink-muted">
          <input
            type="radio"
            name={`save-target-${versionId}`}
            checked={saveTarget === "increment"}
            disabled={busy}
            onChange={() => setSaveTarget("increment")}
          />
          New version of {name} (recommended)
        </label>
        <label className="flex items-center gap-2 text-ink-muted">
          <input
            type="radio"
            name={`save-target-${versionId}`}
            checked={saveTarget === "duplicate"}
            disabled={busy}
            onChange={() => setSaveTarget("duplicate")}
          />
          New strategy (duplicate) — keep {name} untouched
        </label>
        {saveTarget === "duplicate" && (
          <input
            autoFocus
            className={inputCls}
            placeholder="e.g. gold_ema_pullback_v2"
            value={duplicateName}
            disabled={busy}
            onChange={(e) => setDuplicateName(e.target.value)}
          />
        )}
      </div>
    );
  }

  return (
    <section className="rounded-md border border-line bg-panel">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2 text-sm text-ink-muted">
        <span>Source code</span>
        <div className="flex gap-2">
          {(mode === "view" || mode === "edit") && (
            <button
              type="button"
              className={`${btnCls} transition-colors ${
                copied ? "border-ok text-ok hover:border-ok hover:text-ok" : ""
              }`}
              onClick={handleCopy}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          )}
          {mode === "view" && (
            <>
              <button type="button" className={btnCls} onClick={startEdit}>
                Edit
              </button>
              <button type="button" className={btnAccentCls} onClick={startRegenerate}>
                Regenerate with AI
              </button>
            </>
          )}
          {mode !== "view" && (
            <button type="button" className={btnCls} disabled={busy} onClick={cancel}>
              Cancel
            </button>
          )}
        </div>
      </header>

      {mode === "regenerate" && (
        <div className="flex flex-col gap-3 border-b border-line p-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-ink-muted">
              Describe the change — the AI rewrites the full file and it goes through the
              sandbox before anything is saved.
            </span>
            <textarea
              autoFocus
              className={`${inputCls} min-h-20 resize-y`}
              value={instructions}
              disabled={busy}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. only trade during the London session, or tighten the stop loss to 1.5x ATR"
            />
          </label>

          {spec && (
            <div className="flex flex-col gap-2 rounded border border-line p-2">
              <button
                type="button"
                className="cursor-pointer text-left text-xs text-ink-muted hover:text-accent"
                onClick={() => setSpecOpen((o) => !o)}
              >
                {specOpen ? "▾" : "▸"} Edit spec snapshot before regenerating
              </button>
              {specOpen && (
                <div className="flex flex-col gap-2 text-xs">
                  <label className="flex flex-col gap-1">
                    <span className="text-ink-muted">Symbols</span>
                    <SymbolMultiSelect
                      value={specDraft.symbols}
                      onChange={(symbols) => setSpecDraft((s) => ({ ...s, symbols }))}
                      disabled={busy}
                    />
                  </label>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-ink-muted">Entry timeframe</span>
                      <input
                        className={inputCls}
                        value={specDraft.entryTimeframe}
                        disabled={busy}
                        onChange={(e) =>
                          setSpecDraft((s) => ({ ...s, entryTimeframe: e.target.value }))
                        }
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-ink-muted">Confirmation timeframes (comma-separated)</span>
                      <input
                        className={inputCls}
                        value={specDraft.confirmationTimeframes}
                        disabled={busy}
                        onChange={(e) =>
                          setSpecDraft((s) => ({ ...s, confirmationTimeframes: e.target.value }))
                        }
                      />
                    </label>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-ink-muted">Entry rules</span>
                    <textarea
                      className={`${inputCls} min-h-16 resize-y`}
                      value={specDraft.entryRules}
                      disabled={busy}
                      onChange={(e) => setSpecDraft((s) => ({ ...s, entryRules: e.target.value }))}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-ink-muted">Exit rules</span>
                    <textarea
                      className={`${inputCls} min-h-16 resize-y`}
                      value={specDraft.exitRules}
                      disabled={busy}
                      onChange={(e) => setSpecDraft((s) => ({ ...s, exitRules: e.target.value }))}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-ink-muted">Risk notes (informational only — real caps live in configs/risk.yaml)</span>
                    <textarea
                      className={`${inputCls} min-h-12 resize-y`}
                      value={specDraft.riskNotes}
                      disabled={busy}
                      onChange={(e) => setSpecDraft((s) => ({ ...s, riskNotes: e.target.value }))}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-ink-muted">Params (JSON)</span>
                    <textarea
                      className={`${inputCls} min-h-16 resize-y font-mono`}
                      value={specDraft.paramsJson}
                      disabled={busy}
                      onChange={(e) => setSpecDraft((s) => ({ ...s, paramsJson: e.target.value }))}
                    />
                  </label>
                  {(spec.indicators.length > 0 ||
                    spec.price_levels.length > 0 ||
                    spec.chart_notes.length > 0 ||
                    spec.unrecognized_indicators.length > 0) && (
                    <div className="rounded border border-line bg-bg p-2 text-ink-muted">
                      <p className="mb-1">
                        Also sent to the AI unchanged (not editable here):
                      </p>
                      <dl className="flex flex-col gap-0.5">
                        {spec.indicators.length > 0 && (
                          <div>
                            <dt className="inline text-ink">Indicators: </dt>
                            <dd className="inline">
                              {spec.indicators.map((i) => i.label).join(", ")}
                            </dd>
                          </div>
                        )}
                        {spec.unrecognized_indicators.length > 0 && (
                          <div>
                            <dt className="inline text-ink">Other indicators: </dt>
                            <dd className="inline">{spec.unrecognized_indicators.join(", ")}</dd>
                          </div>
                        )}
                        {spec.price_levels.length > 0 && (
                          <div>
                            <dt className="inline text-ink">Price levels: </dt>
                            <dd className="inline">
                              {spec.price_levels.map((l) => `${l.type} @ ${l.price}`).join(", ")}
                            </dd>
                          </div>
                        )}
                        {spec.chart_notes.length > 0 && (
                          <div>
                            <dt className="inline text-ink">Chart notes: </dt>
                            <dd className="inline">{spec.chart_notes.join(", ")}</dd>
                          </div>
                        )}
                      </dl>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {saveDestinationFields()}

          <div className="flex gap-2">
            <button type="button" className={btnAccentCls} disabled={busy} onClick={onRegenerate}>
              {busy ? "Regenerating…" : "Regenerate"}
            </button>
          </div>
        </div>
      )}

      {(error || sandboxErrors.length > 0) && (
        <div className="border-b border-line px-3 py-2 text-xs text-err">
          {error && <p>{error}</p>}
          {sandboxErrors.length > 0 && (
            <>
              <p className="mt-1 text-ink-muted">
                The AI&apos;s proposal failed sandbox validation — dropped into the editor below
                for a manual fix:
              </p>
              <ul className="list-inside list-disc">
                {sandboxErrors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {mode === "edit" ? (
        <>
          <CodeMirror
            value={draft}
            height="32rem"
            theme={cmTheme}
            extensions={[python()]}
            onChange={setDraft}
          />
          <div className="flex flex-col gap-3 border-t border-line p-3">
            {saveDestinationFields()}
            <div className="flex gap-2">
              <button type="button" className={btnAccentCls} disabled={busy} onClick={onSaveEdit}>
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </>
      ) : (
        mode === "view" && <pre className="max-h-[32rem] overflow-auto p-3 text-xs">{code}</pre>
      )}
    </section>
  );
}

const inputCls =
  "rounded border border-line bg-bg px-2 py-1 text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";
const btnCls =
  "cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50";
const btnAccentCls =
  "cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50";
