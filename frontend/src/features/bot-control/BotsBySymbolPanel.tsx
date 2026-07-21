"use client";

/**
 * Running bots grouped by symbol, with each bot's currently attributed open
 * position(s) and floating P/L — the single place to see what's live on a
 * symbol and flatten it. "Close" here is stronger than the Stop button on
 * `/bots` (SymbolAssignmentPanel): it both deactivates the bot's routing
 * (removeBotFromSymbol) and flattens every open position it currently holds,
 * so nothing is left running or exposed. Supports closing one bot, a
 * selected subset on a symbol, or every bot on a symbol.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  closePosition,
  getSkillAssignments,
  removeBotFromSymbol,
  type NormalSkillAssignment,
  type PositionOut,
} from "@/shared/api/client";
import { useAllPositions } from "@/features/trading/useAllPositions";

interface BotWithPositions {
  bot: NormalSkillAssignment;
  positions: PositionOut[];
  profit: number;
}

async function closeBotAndPositions(
  symbol: string,
  botWithPositions: BotWithPositions,
  onError: (message: string) => void,
): Promise<void> {
  let allClosed = true;
  for (const position of botWithPositions.positions) {
    try {
      await closePosition(position.ticket);
    } catch (e) {
      allClosed = false;
      onError(
        e instanceof ApiError
          ? `#${position.ticket} (${symbol}): ${e.message}`
          : `#${position.ticket} (${symbol}): failed to close`,
      );
    }
  }
  if (!allClosed) {
    onError(
      `${botWithPositions.bot.bot_name} on ${symbol}: left active — not every position closed`,
    );
    return;
  }
  try {
    await removeBotFromSymbol(symbol, botWithPositions.bot.bot_name);
  } catch (e) {
    onError(
      e instanceof ApiError
        ? `${botWithPositions.bot.bot_name} on ${symbol}: ${e.message}`
        : `failed to stop ${botWithPositions.bot.bot_name} on ${symbol}`,
    );
  }
}

export function BotsBySymbolPanel() {
  const allPositions = useAllPositions();
  const [assignments, setAssignments] = useState<NormalSkillAssignment[] | null>(null);
  const [filter, setFilter] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [selected, setSelected] = useState<Record<string, Set<string>>>({});

  const refreshAssignments = useCallback(() => {
    getSkillAssignments()
      .then(setAssignments)
      .catch(() => setErrors((prev) => [...prev, "failed to load bot assignments"]));
  }, []);

  useEffect(refreshAssignments, [refreshAssignments]);

  if (assignments === null) {
    return (
      <div className="flex items-center justify-center p-8 text-sm text-ink-muted">
        Loading bots…
      </div>
    );
  }

  const bySymbol = new Map<string, NormalSkillAssignment[]>();
  for (const a of assignments) {
    const bots = bySymbol.get(a.symbol) ?? [];
    bots.push(a);
    bySymbol.set(a.symbol, bots);
  }
  const symbols = Array.from(bySymbol.keys())
    .filter((s) => s.toLowerCase().includes(filter.trim().toLowerCase()))
    .sort();

  function botsWithPositions(symbol: string): BotWithPositions[] {
    return (bySymbol.get(symbol) ?? []).map((bot) => {
      const positions = allPositions.positions.filter(
        (p) => allPositions.skillByTicket.get(String(p.ticket)) === bot.name,
      );
      return { bot, positions, profit: positions.reduce((sum, p) => sum + p.profit, 0) };
    });
  }

  function unassignedPositions(symbol: string): PositionOut[] {
    const botNames = new Set((bySymbol.get(symbol) ?? []).map((b) => b.name));
    return allPositions.positions.filter((p) => {
      if (p.symbol !== symbol) return false;
      const skill = allPositions.skillByTicket.get(String(p.ticket));
      return !skill || !botNames.has(skill);
    });
  }

  function toggleSelected(symbol: string, botName: string) {
    setSelected((prev) => {
      const current = new Set(prev[symbol] ?? []);
      if (current.has(botName)) current.delete(botName);
      else current.add(botName);
      return { ...prev, [symbol]: current };
    });
  }

  function afterAction() {
    refreshAssignments();
    allPositions.refresh();
  }

  async function closeOne(symbol: string, entry: BotWithPositions) {
    if (
      !window.confirm(
        `Close bot "${entry.bot.bot_name}" on ${symbol}? This stops it trading and closes ` +
          `${entry.positions.length} open position(s).`,
      )
    ) {
      return;
    }
    setBusyKey(`${symbol}:${entry.bot.bot_name}`);
    try {
      await closeBotAndPositions(symbol, entry, (msg) => setErrors((prev) => [...prev, msg]));
      afterAction();
    } finally {
      setBusyKey(null);
    }
  }

  async function closeMany(symbol: string, entries: BotWithPositions[], confirmMessage: string) {
    if (entries.length === 0) return;
    if (!window.confirm(confirmMessage)) return;
    setBusyKey(symbol);
    try {
      for (const entry of entries) {
        await closeBotAndPositions(symbol, entry, (msg) => setErrors((prev) => [...prev, msg]));
      }
      setSelected((prev) => ({ ...prev, [symbol]: new Set() }));
      afterAction();
    } finally {
      setBusyKey(null);
    }
  }

  function closeAllOnSymbol(symbol: string) {
    const entries = botsWithPositions(symbol);
    const totalPositions = entries.reduce((sum, e) => sum + e.positions.length, 0);
    return closeMany(
      symbol,
      entries,
      `Close all ${entries.length} bot(s) on ${symbol}? This stops them trading and closes ` +
        `${totalPositions} open position(s) total.`,
    );
  }

  function closeSelected(symbol: string) {
    const selectedNames = selected[symbol] ?? new Set();
    const entries = botsWithPositions(symbol).filter((e) => selectedNames.has(e.bot.bot_name));
    const totalPositions = entries.reduce((sum, e) => sum + e.positions.length, 0);
    return closeMany(
      symbol,
      entries,
      `Close ${entries.length} selected bot(s) on ${symbol}? This stops them trading and closes ` +
        `${totalPositions} open position(s) total.`,
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by symbol…"
          className="w-64 rounded border border-line bg-panel/60 px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none"
        />
        <span className="text-xs text-ink-muted">
          {symbols.length} symbol{symbols.length === 1 ? "" : "s"} with active bots
        </span>
      </div>

      {errors.length > 0 && (
        <div className="rounded-lg border border-err/30 bg-err/10 p-3 text-sm text-err">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold">⚠️ Errors</span>
            <button
              type="button"
              className="text-xs font-semibold hover:underline"
              onClick={() => setErrors([])}
            >
              Dismiss
            </button>
          </div>
          <ul className="list-inside list-disc space-y-0.5">
            {errors.map((msg, i) => (
              <li key={i}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      {symbols.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center rounded-xl border border-line bg-panel/30">
          <p className="text-sm font-semibold text-ink">No matching symbols</p>
          <p className="text-xs text-ink-muted mt-1">
            {assignments.length === 0
              ? "No bots are currently active on any symbol."
              : "Try a different filter."}
          </p>
        </div>
      ) : (
        <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
          {symbols.map((symbol) => {
            const entries = botsWithPositions(symbol);
            const unassigned = unassignedPositions(symbol);
            const totalProfit =
              entries.reduce((sum, e) => sum + e.profit, 0) +
              unassigned.reduce((sum, p) => sum + p.profit, 0);
            const totalPositionCount =
              entries.reduce((sum, e) => sum + e.positions.length, 0) + unassigned.length;
            const symbolBusy = busyKey === symbol;
            const selectedCount = selected[symbol]?.size ?? 0;

            return (
              <div
                key={symbol}
                className="rounded-xl border border-line bg-panel p-4 shadow-md"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-bold text-ink tracking-wider bg-bg px-2 py-1 rounded">
                    {symbol}
                  </span>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-ink-muted">
                      {totalPositionCount} open position{totalPositionCount === 1 ? "" : "s"}
                    </span>
                    <span
                      className={`font-bold ${totalProfit >= 0 ? "text-ok" : "text-err"}`}
                    >
                      {totalProfit >= 0 ? "+" : ""}
                      {totalProfit.toFixed(2)}
                    </span>
                  </div>
                </div>

                <div className="flex flex-col gap-2">
                  {entries.map((entry) => {
                    const key = `${symbol}:${entry.bot.bot_name}`;
                    const isBusy = busyKey === key || symbolBusy;
                    const isSelected = selected[symbol]?.has(entry.bot.bot_name) ?? false;
                    return (
                      <div
                        key={entry.bot.bot_name}
                        className={`rounded-lg border p-2 ${
                          isBusy ? "border-accent ring-1 ring-accent" : "border-line"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <label className="flex min-w-0 items-center gap-2">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              disabled={busyKey !== null}
                              onChange={() => toggleSelected(symbol, entry.bot.bot_name)}
                            />
                            <span
                              className="truncate text-xs font-semibold text-ink"
                              title={entry.bot.bot_name}
                            >
                              {entry.bot.bot_name}
                            </span>
                            <span className="shrink-0 text-3xs text-ink-muted">
                              {entry.bot.strategy}
                            </span>
                          </label>
                          <button
                            type="button"
                            className="shrink-0 text-3xs font-semibold text-err hover:underline disabled:opacity-40"
                            disabled={busyKey !== null}
                            onClick={() => closeOne(symbol, entry)}
                          >
                            {busyKey === key ? "…" : "Close"}
                          </button>
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-3xs text-ink-muted">
                          <span>
                            {entry.positions.length} position
                            {entry.positions.length === 1 ? "" : "s"}
                          </span>
                          {entry.positions.length > 0 && (
                            <span
                              className={`font-semibold ${
                                entry.profit >= 0 ? "text-ok" : "text-err"
                              }`}
                            >
                              {entry.profit >= 0 ? "+" : ""}
                              {entry.profit.toFixed(2)}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {unassigned.length > 0 && (
                  <p className="mt-2 text-3xs text-ink-muted">
                    {unassigned.length} manual position{unassigned.length === 1 ? "" : "s"} on
                    this symbol, not attributed to a bot — not affected by bot actions here.
                  </p>
                )}

                <div className="mt-3 flex items-center gap-2">
                  <button
                    type="button"
                    className="flex-1 rounded border border-err/60 px-2 py-1.5 text-3xs font-semibold text-err hover:bg-err hover:text-bg disabled:opacity-40"
                    disabled={busyKey !== null || entries.length === 0}
                    onClick={() => closeAllOnSymbol(symbol)}
                  >
                    {symbolBusy ? "…" : `Close all ${entries.length} bot(s)`}
                  </button>
                  <button
                    type="button"
                    className="flex-1 rounded border border-line px-2 py-1.5 text-3xs font-semibold text-ink-muted hover:text-ink hover:border-line-hover disabled:opacity-40"
                    disabled={busyKey !== null || selectedCount === 0}
                    onClick={() => closeSelected(symbol)}
                  >
                    Close selected ({selectedCount})
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
