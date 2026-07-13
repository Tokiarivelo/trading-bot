"use client";

/** Inline code editor for the bot behind a backtest report (§backtest UX):
 * edit the strategy's source right here and re-run the same symbol/period
 * on save — the report/chart above updates in place via a URL replace to
 * the new report id, no trip to the strategies section required. Each save
 * increments the same strategy family (never forks), so repeated edits
 * build on the version just saved rather than the original. Hidden for
 * `breakout_v1`, the hardcoded baseline with no DB-backed version to edit. */

import { python } from "@codemirror/lang-python";
import { githubDarkInit } from "@uiw/codemirror-theme-github";
import CodeMirror from "@uiw/react-codemirror";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  editStrategyVersionCode,
  getBacktestJobStatus,
  getStrategyVersion,
  getStrategyVersions,
  startBacktest,
  type StrategyVersionSummary,
} from "@/shared/api/client";

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

type Phase = "idle" | "saving" | "backtesting";

export function BacktestStrategyEditor({
  strategyName,
  symbol,
  period,
  onSaved,
  className,
}: {
  strategyName: string;
  symbol: string;
  period: string;
  /** When set, called with the new report id instead of navigating to
   * `/backtest/[id]` — used when this editor is embedded somewhere that
   * already renders the report in place (e.g. the chart's backtest view)
   * and just needs to swap which report id it's showing. */
  onSaved?: (reportId: string) => void;
  className?: string;
}) {
  const router = useRouter();
  const [baseVersion, setBaseVersion] = useState<StrategyVersionSummary | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [sandboxErrors, setSandboxErrors] = useState<string[]>([]);
  const mountedRef = useRef(true);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(draft);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  useEffect(() => () => { mountedRef.current = false; }, []);

  useEffect(() => {
    setBaseVersion(null);
    setLoadErr(null);
    setEditing(false);
    if (strategyName === "breakout_v1") return;
    getStrategyVersions(strategyName)
      .then((versions) => {
        // Newest first per name; prefer whichever's active so edits build on
        // the version actually driving live trading, not a stale draft.
        const pick = versions.find((v) => v.status === "active") ?? versions[0] ?? null;
        setBaseVersion(pick);
        if (pick === null) setLoadErr("no editable version found for this strategy");
      })
      .catch(() => setLoadErr("failed to load strategy version"));
  }, [strategyName]);

  async function startEditing() {
    if (!baseVersion) return;
    setError(null);
    setSandboxErrors([]);
    try {
      const detail = await getStrategyVersion(baseVersion.id);
      setDraft(detail.code);
      setEditing(true);
    } catch {
      setError("failed to load source code");
    }
  }

  async function onSave() {
    if (!baseVersion) return;
    setError(null);
    setSandboxErrors([]);
    setPhase("saving");
    try {
      const saved = await editStrategyVersionCode(baseVersion.id, draft);
      setPhase("backtesting");
      const job = await startBacktest(saved.id, symbol, period);
      await pollUntilDone(job.job_id);
    } catch (e) {
      if (!mountedRef.current) return;
      if (e instanceof ApiError && e.status === 422) {
        setSandboxErrors(e.message.split("; "));
      } else {
        setError(e instanceof Error ? e.message : "save failed");
      }
      setPhase("idle");
    }
  }

  async function pollUntilDone(jobId: string): Promise<void> {
    const job = await getBacktestJobStatus(jobId);
    if (!mountedRef.current) return;
    if (job.status === "done" && job.report_id) {
      setPhase("idle");
      setEditing(false);
      if (onSaved) {
        onSaved(job.report_id);
      } else {
        router.replace(`/backtest/${encodeURIComponent(job.report_id)}`);
      }
      return;
    }
    if (job.status === "error") {
      setError(job.error ?? "backtest failed");
      setPhase("idle");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (!mountedRef.current) return;
    return pollUntilDone(jobId);
  }

  if (strategyName === "breakout_v1") return null;
  if (loadErr) return null;
  if (!baseVersion) return null;

  const busy = phase !== "idle";

  return (
    <section className={`rounded-md border border-line bg-panel flex flex-col ${className || ""}`}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2 text-sm text-ink-muted shrink-0">
        <span>Strategy code</span>
        <div className="flex gap-2">
          {editing && (
            <button
              type="button"
              className={`cursor-pointer rounded border border-line px-2 py-1 text-xs transition-colors ${
                copied
                  ? "border-ok text-ok hover:border-ok hover:text-ok"
                  : "hover:border-accent hover:text-accent"
              }`}
              onClick={handleCopy}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          )}
          {!editing ? (
            <button
              type="button"
              className="cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent"
              onClick={startEditing}
            >
              Edit
            </button>
          ) : (
            <button
              type="button"
              className="cursor-pointer rounded border border-line px-2 py-1 text-xs hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          )}
        </div>
      </header>

      {editing && (
        <div className="flex flex-col flex-1 min-h-0">
          <CodeMirror
            value={draft}
            height="100%"
            className="flex-1 min-h-0 overflow-auto"
            theme={cmTheme}
            extensions={[python()]}
            onChange={setDraft}
            editable={!busy}
          />
          {(error || sandboxErrors.length > 0) && (
            <div className="border-t border-line px-3 py-2 text-xs text-err shrink-0">
              {error && <p>{error}</p>}
              {sandboxErrors.length > 0 && (
                <>
                  <p className="mt-1 text-ink-muted">Sandbox validation failed:</p>
                  <ul className="list-inside list-disc">
                    {sandboxErrors.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
          <div className="flex items-center gap-2 border-t border-line p-3 shrink-0">
            <button
              type="button"
              className="cursor-pointer rounded border border-accent px-3 py-1 text-xs text-accent hover:bg-accent hover:text-bg disabled:cursor-not-allowed disabled:opacity-50"
              disabled={busy}
              onClick={onSave}
            >
              {phase === "saving" && "Validating & saving…"}
              {phase === "backtesting" && "Re-running backtest…"}
              {phase === "idle" && "Save & re-run backtest"}
            </button>
            <span className="text-xs text-ink-muted">
              Saves as the next version of {strategyName}, then re-runs {symbol} {period} and
              refreshes this report.
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
