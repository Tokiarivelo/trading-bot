"use client";

/**
 * The real "activate bots on a symbol" control (§6.6): shows every symbol
 * currently routed for live trading, grouped by symbol, with every
 * concurrently-active bot on it (skills/normal/<symbol>/<bot_name>.yaml,
 * what TradeEngine._try_enter actually reads via SkillSelector — including
 * any bot activated at runtime via BotSelector, not just ones configured at
 * backend startup). Each bot can be independently reassigned to another
 * strategy family or stopped, and a symbol's card lets a trader add another
 * bot alongside whatever's already running. Every change here writes the
 * YAML and hot-swaps the live selector immediately — no restart needed.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  addBotToSymbol,
  getLiveBotSignals,
  getSkillAssignments,
  getStrategyVersions,
  getSymbolSpreadConfig,
  putSymbolMinRr,
  removeBotFromSymbol,
  updateBotAssignment,
  type BacktestSignal,
  type NormalSkillAssignment,
} from "@/shared/api/client";
import { BotConfigEditor } from "./BotConfigEditor";

/** Per-bot signal→outcome tally for the activity badge below (last 14 days,
 * `getLiveBotSignals`'s default window). `confirmed` counts every signal the
 * strategy emitted; `opened`/`rejected` split its outcomes into "became a
 * trade" vs. "vetoed or rejected" (htf_veto/risk_rejected/spread_veto/
 * broker_rejected) — `skipped` (no outcome logged yet) counts toward
 * `confirmed` only. */
interface BotSignalCounts {
  confirmed: number;
  opened: number;
  rejected: number;
}

function summarizeSignals(signals: BacktestSignal[]): BotSignalCounts {
  let opened = 0;
  let rejected = 0;
  for (const s of signals) {
    if (s.outcome === "opened") opened += 1;
    else if (s.outcome !== "skipped") rejected += 1;
  }
  return { confirmed: signals.length, opened, rejected };
}

export function SymbolAssignmentPanel() {
  const [assignments, setAssignments] = useState<NormalSkillAssignment[] | null>(null);
  const [activeBots, setActiveBots] = useState<string[] | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newBotStrategy, setNewBotStrategy] = useState<Record<string, string>>({});
  const [signalCounts, setSignalCounts] = useState<Map<string, BotSignalCounts>>(new Map());
  const [configuringKey, setConfiguringKey] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([getSkillAssignments(), getStrategyVersions(undefined, "active")])
      .then(([skills, versions]) => {
        setAssignments(skills);
        setActiveBots(Array.from(new Set(versions.map((v) => v.name))).sort());
        Promise.all(
          skills.map((a) =>
            getLiveBotSignals(a.name)
              .then((signals): [string, BotSignalCounts] => [a.name, summarizeSignals(signals)])
              .catch((): [string, BotSignalCounts] => [a.name, { confirmed: 0, opened: 0, rejected: 0 }]),
          ),
        ).then((entries) => setSignalCounts(new Map(entries)));
      })
      .catch(() => setError("failed to load symbol assignments"));
  }, []);

  useEffect(refresh, [refresh]);

  async function reassign(symbol: string, botName: string, strategyName: string) {
    setBusyKey(`${symbol}:${botName}`);
    setError(null);
    try {
      await updateBotAssignment(symbol, botName, strategyName);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `failed to reassign ${botName} on ${symbol}`);
    } finally {
      setBusyKey(null);
    }
  }

  async function stop(symbol: string, botName: string) {
    setBusyKey(`${symbol}:${botName}`);
    setError(null);
    try {
      await removeBotFromSymbol(symbol, botName);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `failed to stop ${botName} on ${symbol}`);
    } finally {
      setBusyKey(null);
    }
  }

  async function addBot(symbol: string, fallbackStrategy: string | undefined) {
    const strategyName = newBotStrategy[symbol] ?? fallbackStrategy;
    if (!strategyName) return;
    setBusyKey(`${symbol}:__new__`);
    setError(null);
    try {
      await addBotToSymbol(symbol, strategyName);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `failed to add a bot to ${symbol}`);
    } finally {
      setBusyKey(null);
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

  const bySymbol = new Map<string, NormalSkillAssignment[]>();
  for (const a of assignments) {
    const bots = bySymbol.get(a.symbol) ?? [];
    bots.push(a);
    bySymbol.set(a.symbol, bots);
  }
  const symbols = Array.from(bySymbol.keys()).sort();

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-start gap-3 rounded-lg border border-ok/20 bg-ok/5 p-4 text-xs text-ok">
        <svg className="h-5 w-5 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <div>
          <span className="font-semibold block mb-0.5">Live Connection Router</span>
          Changes to bot assignments below write to backend configuration and hot-swap active trading rules immediately. No restart of the Trade Engine or MT5 bridge is required. A symbol can run several bots concurrently, each independently trading its own strategy.
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-err/30 bg-err/10 p-3 text-sm text-err font-medium">
          ⚠️ {error}
        </div>
      )}

      {symbols.length === 0 ? (
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
          {symbols.map((symbol) => {
            const bots = bySymbol.get(symbol)!;
            const addBusy = busyKey === `${symbol}:__new__`;
            return (
              <div
                key={symbol}
                className="relative overflow-hidden rounded-xl border border-line p-4 bg-panel shadow-md transition-all duration-200 hover:border-line-hover"
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-sm font-bold text-ink tracking-wider bg-bg px-2 py-1 rounded">
                    {symbol}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-ok animate-pulse" />
                    <span className="text-3xs font-semibold text-ok uppercase tracking-wider">
                      {bots.length} bot{bots.length === 1 ? "" : "s"} live
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  {bots.map((bot) => {
                    const key = `${symbol}:${bot.bot_name}`;
                    const isBusy = busyKey === key;
                    return (
                      <div
                        key={bot.bot_name}
                        className={`rounded-lg border p-2 transition-all duration-200 ${
                          isBusy ? "border-accent ring-1 ring-accent" : "border-line"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span
                            className="text-xs font-semibold text-ink truncate"
                            title={bot.bot_name}
                          >
                            {bot.bot_name}
                          </span>
                          <div className="flex shrink-0 items-center gap-2">
                            <button
                              type="button"
                              className="text-3xs font-semibold text-accent hover:underline"
                              onClick={() => setConfiguringKey(configuringKey === key ? null : key)}
                            >
                              {configuringKey === key ? "Hide" : "Configure"}
                            </button>
                            <button
                              type="button"
                              className="text-3xs font-semibold text-err hover:underline disabled:opacity-40"
                              disabled={busyKey !== null}
                              onClick={() => stop(symbol, bot.bot_name)}
                            >
                              {isBusy ? "…" : "Stop"}
                            </button>
                          </div>
                        </div>
                        <BotSignalBadge counts={signalCounts.get(bot.name)} />
                        <select
                          className="w-full rounded border border-line bg-bg/80 px-2 py-1 text-xs text-ink focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none disabled:opacity-50 transition-all duration-200"
                          value={bot.strategy}
                          disabled={busyKey !== null}
                          onChange={(e) => reassign(symbol, bot.bot_name, e.target.value)}
                        >
                          {!activeBots.includes(bot.strategy) && (
                            <option value={bot.strategy}>{bot.strategy} (Inactive)</option>
                          )}
                          {activeBots.map((name) => (
                            <option key={name} value={name}>
                              {name}
                            </option>
                          ))}
                        </select>
                        {configuringKey === key && (
                          <BotConfigEditor
                            symbol={symbol}
                            bot={bot}
                            onSaved={() => {
                              setConfiguringKey(null);
                              refresh();
                            }}
                          />
                        )}
                      </div>
                    );
                  })}
                </div>

                {activeBots.length > 0 && (
                  <div className="mt-3 flex items-center gap-1.5">
                    <select
                      className="flex-1 min-w-0 rounded border border-line bg-bg/80 px-2 py-1 text-xs text-ink focus:border-accent focus:outline-none disabled:opacity-50"
                      value={newBotStrategy[symbol] ?? activeBots[0]}
                      disabled={busyKey !== null}
                      onChange={(e) =>
                        setNewBotStrategy((prev) => ({ ...prev, [symbol]: e.target.value }))
                      }
                    >
                      {activeBots.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="shrink-0 rounded border border-accent px-2 py-1 text-3xs font-semibold text-accent hover:bg-accent hover:text-bg disabled:opacity-40"
                      disabled={busyKey !== null}
                      onClick={() => addBot(symbol, activeBots[0])}
                    >
                      {addBusy ? "…" : "+ Add bot"}
                    </button>
                  </div>
                )}

                <SymbolMinRrEditor symbol={symbol} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Activity badge for one bot card: how many signals its strategy confirmed,
 * how many became trades, and how many were vetoed/rejected, over the last
 * 14 days (`GET /activity/signals`'s default window) — lets a trader
 * eyeball which of several concurrently-active bots is actually doing
 * anything without opening the activity log. `undefined` while its own
 * fetch is still in flight. */
function BotSignalBadge({ counts }: { counts: BotSignalCounts | undefined }) {
  if (!counts) {
    return <p className="mb-1.5 text-3xs text-ink-muted">Loading activity…</p>;
  }
  return (
    <div className="mb-1.5 flex items-center gap-1">
      <span
        className="rounded border border-accent/20 bg-accent/10 px-1 py-0.5 text-3xs font-semibold text-accent"
        title="Signals confirmed by this bot's strategy (last 14 days)"
      >
        {counts.confirmed} signal{counts.confirmed === 1 ? "" : "s"}
      </span>
      <span
        className="rounded border border-ok/20 bg-ok/10 px-1 py-0.5 text-3xs font-semibold text-ok"
        title="Signals that became trades"
      >
        {counts.opened} opened
      </span>
      <span
        className="rounded border border-err/20 bg-err/10 px-1 py-0.5 text-3xs font-semibold text-err"
        title="Signals vetoed or rejected (HTF veto, risk sizing, spread/RR gate, broker)"
      >
        {counts.rejected} rejected
      </span>
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
