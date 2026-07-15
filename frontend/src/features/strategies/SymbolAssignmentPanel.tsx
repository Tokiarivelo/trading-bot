"use client";

/**
 * The real "apply a bot to a symbol" control (§6.6): shows every symbol
 * currently routed for live trading (skills/normal/<symbol>.yaml, what
 * TradeEngine._try_enter actually reads via SkillSelector — including any
 * symbol activated at runtime via BotSelector, not just ones configured at
 * backend startup) and lets the trader reroute it to any other
 * currently-active bot family. Reassigning here writes the YAML and
 * hot-swaps the live selector immediately — no restart needed.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  assignStrategyToSymbol,
  getSkillAssignments,
  getStrategyVersions,
  getSymbolSpreadConfig,
  putSymbolMinRr,
  type NormalSkillAssignment,
} from "@/shared/api/client";

export function SymbolAssignmentPanel() {
  const [assignments, setAssignments] = useState<NormalSkillAssignment[] | null>(null);
  const [activeBots, setActiveBots] = useState<string[] | null>(null);
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([getSkillAssignments(), getStrategyVersions(undefined, "active")])
      .then(([skills, versions]) => {
        setAssignments(skills);
        setActiveBots(Array.from(new Set(versions.map((v) => v.name))).sort());
      })
      .catch(() => setError("failed to load symbol assignments"));
  }, []);

  useEffect(refresh, [refresh]);

  async function reassign(symbol: string, strategyName: string) {
    setBusySymbol(symbol);
    setError(null);
    try {
      await assignStrategyToSymbol(symbol, strategyName);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `failed to reassign ${symbol}`);
    } finally {
      setBusySymbol(null);
    }
  }

  if (assignments === null || activeBots === null) {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-ink-muted">
        <svg className="animate-spin h-5 w-5 text-accent mr-2" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        Loading live connections...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-start gap-3 rounded-lg border border-ok/20 bg-ok/5 p-4 text-xs text-ok">
        <svg className="h-5 w-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <div>
          <span className="font-semibold block mb-0.5">Live Connection Router</span>
          Changes to symbol assignments below write to backend configuration and hot-swap active trading rules immediately. No restart of the Trade Engine or MT5 bridge is required.
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-err/30 bg-err/10 p-3 text-sm text-err font-medium">
          ⚠️ {error}
        </div>
      )}

      {assignments.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center rounded-xl border border-line bg-panel/30">
          <svg className="h-10 w-10 text-ink-muted mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
          <p className="text-sm font-semibold text-ink">No symbols connected yet</p>
          <p className="text-xs text-ink-muted mt-1 max-w-xs">
            Connect your first bot to a symbol on the Chart screen or by activating a strategy.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {assignments.map((a) => {
            const isBusy = busySymbol === a.symbol;
            return (
              <div
                key={a.symbol}
                className={`relative overflow-hidden rounded-xl border p-4 bg-panel shadow-md transition-all duration-200 ${
                  isBusy ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-hover"
                }`}
              >
                {/* Header */}
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-bold text-ink tracking-wider bg-bg px-2 py-1 rounded">
                    {a.symbol}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-ok animate-pulse" />
                    <span className="text-3xs font-semibold text-ok uppercase tracking-wider">Live</span>
                  </div>
                </div>

                {/* Body Selector */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wider">
                    Assigned Bot Family
                  </label>
                  <div className="relative">
                    <select
                      className="w-full rounded-lg border border-line bg-bg/80 px-3 py-2 text-sm text-ink focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none disabled:opacity-50 transition-all duration-200"
                      value={a.strategy}
                      disabled={busySymbol !== null}
                      onChange={(e) => reassign(a.symbol, e.target.value)}
                    >
                      {!activeBots.includes(a.strategy) && (
                        <option value={a.strategy}>{a.strategy} (Inactive)</option>
                      )}
                      {activeBots.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <SymbolMinRrEditor symbol={a.symbol} />

                {/* Busy overlay */}
                {isBusy && (
                  <div className="absolute inset-0 bg-panel/85 flex items-center justify-center backdrop-blur-xs">
                    <div className="flex items-center gap-2 text-xs font-semibold text-accent">
                      <svg className="animate-spin h-4 w-4 text-accent" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      Applying...
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Inline editor for one symbol's live `min_rr` (the spread-adjusted
 * reward:risk floor `SpreadGate.check()` enforces) — a tighter-stop
 * strategy (e.g. a scalping variant) can fail the RR floor a swing-trading
 * min_rr was tuned for, so this lets it be retuned without a restart. Not
 * persisted: a backend restart reverts to configs/symbols/<symbol>.yaml. */
function SymbolMinRrEditor({ symbol }: { symbol: string }) {
  const [minRr, setMinRr] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSymbolSpreadConfig(symbol)
      .then((c) => {
        setMinRr(c.min_rr);
        setDraft(String(c.min_rr));
      })
      .catch(() => setError("no spread config"));
  }, [symbol]);

  const parsed = Number(draft);
  const isValid = draft.trim() !== "" && Number.isFinite(parsed) && parsed > 0;
  const isDirty = minRr !== null && isValid && parsed !== minRr;

  async function save() {
    if (!isValid) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await putSymbolMinRr(symbol, parsed);
      setMinRr(updated.min_rr);
      setDraft(String(updated.min_rr));
    } catch {
      setError("failed to update min_rr");
    } finally {
      setSaving(false);
    }
  }

  if (error && minRr === null) {
    return <p className="mt-2 text-[10px] text-ink-muted">{error}</p>;
  }
  if (minRr === null) {
    return <p className="mt-2 text-[10px] text-ink-muted">Loading min RR…</p>;
  }

  return (
    <div className="mt-2 flex items-center gap-1.5">
      <label className="text-[10px] font-semibold text-ink-muted uppercase tracking-wider">
        Min RR
      </label>
      <input
        type="number"
        min="0"
        step="0.1"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="w-16 rounded border border-line bg-bg/80 px-1.5 py-0.5 text-xs text-ink focus:border-accent focus:outline-none"
      />
      <button
        type="button"
        disabled={!isDirty || saving}
        onClick={save}
        className="rounded border border-accent px-1.5 py-0.5 text-[10px] text-accent disabled:opacity-40"
      >
        {saving ? "…" : "Save"}
      </button>
      {error && <span className="text-[10px] text-err">{error}</span>}
    </div>
  );
}
