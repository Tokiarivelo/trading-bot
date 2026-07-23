"use client";

/**
 * Chart-page bot picker for the active symbol (§5/§6.5, §6.6): shows every
 * bot currently routed to trade this symbol live — read from the skill
 * assignments (skills/normal/<symbol>/*.yaml via GET /skills/normal), not
 * just "some active version whose spec happens to list this symbol" — and
 * lets the trader activate another bot alongside them, or stop one.
 *
 * Activating a bot from a *different* family than what's currently routed
 * both activates that family's version (if it isn't already the live one)
 * and adds it as a new bot on the symbol via addBotToSymbol — it never
 * replaces a bot already running here; several bots can trade the same
 * symbol concurrently, each independently.
 *
 * Each active bot also gets an eye icon: toggles that bot's live signal
 * trail (every setup it saw, opened or vetoed/rejected) and its own
 * positions/profit as a chart overlay — the state itself lives in the
 * parent page (mirrors how it already owns `backtestReportId` for the
 * backtest-view overlay) so `ChartPanel` can read it directly.
 */

import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  ApiError,
  activateStrategyVersion,
  addBotToSymbol,
  getLiveBotSignals,
  getSkillAssignments,
  getStrategyVersions,
  getTradeMarkers,
  removeBotFromSymbol,
  type NormalSkillAssignment,
  type StrategyVersionSummary,
} from "@/shared/api/client";

interface BotCounts {
  signals: number;
  rejected: number;
  orders: number;
  trades: number;
}

// Bot assignments are edited from a different page (`/bots` ->
// SymbolAssignmentPanel), so this panel can't rely on its own actions to know
// when they change — poll like the chart's other "external state" panels
// (spread, markers, news) do, and also refetch the moment this tab regains
// focus so switching back from `/bots` doesn't wait out a full poll tick.
const ASSIGNMENTS_POLL_MS = 5000;

export function BotSelector({
  symbol,
  activeSignalsSkill = null,
  onToggleSignals,
  signalsDisabled = false,
}: {
  symbol: string;
  /** The `skill` (full bot id) whose signals/positions are currently shown
   * on the chart, if any — lets this bot's eye render as "on". */
  activeSignalsSkill?: string | null;
  /** Called with a bot's `skill` when its eye is clicked — toggling the
   * same skill again should turn the overlay off; the parent owns that
   * logic (it also has to clear backtest view when this fires). */
  onToggleSignals?: (skill: string) => void;
  /** True while viewing a backtest report — the live overlay and backtest
   * view are mutually exclusive, so the eye is disabled rather than firing
   * into an ambiguous state. */
  signalsDisabled?: boolean;
}) {
  const accountId = useActiveAccount();
  const [candidates, setCandidates] = useState<StrategyVersionSummary[] | null>(null);
  const [activeBots, setActiveBots] = useState<NormalSkillAssignment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [justActivated, setJustActivated] = useState<string | null>(null);
  const [counts, setCounts] = useState<Record<string, BotCounts>>({});
  const [filter, setFilter] = useState("");

  const refresh = useCallback(() => {
    if (!accountId) return;
    Promise.all([getStrategyVersions(accountId), getSkillAssignments()])
      .then(([versions, assignments]) => {
        setCandidates(
          versions
            .filter((v) => v.status !== "archived" && (v.spec?.symbols ?? []).includes(symbol))
            .sort((a, b) => b.created_at - a.created_at),
        );
        setActiveBots(assignments.filter((a) => a.symbol === symbol));
      })
      .catch(() => setError("failed to load bots for this symbol"));
  }, [accountId, symbol]);

  useEffect(() => {
    setCandidates(null);
    setActiveBots(null);
    setJustActivated(null);
    refresh();
    const timer = setInterval(refresh, ASSIGNMENTS_POLL_MS);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);

  // Per-bot Signals / Orders / Trades chip counts — one journal + one
  // activity-log fetch per active bot, same endpoints the eye overlay
  // already uses for a single bot, just fanned out across the whole list.
  // A failure for one bot (e.g. no signals persisted yet) shouldn't blank
  // out every other bot's counts, so each bot's fetch is caught on its own.
  useEffect(() => {
    if (!activeBots || activeBots.length === 0 || !accountId) return;
    let cancelled = false;
    Promise.all(
      activeBots.map((bot) =>
        Promise.all([
          getTradeMarkers(accountId, symbol, bot.name),
          getLiveBotSignals(accountId, bot.name),
        ])
          .then(([markers, signals]): [string, BotCounts] => [
            bot.name,
            {
              orders: markers.length,
              trades: markers.filter((m) => m.close_time !== null).length,
              signals: signals.length,
              rejected: signals.filter((s) => s.outcome !== "opened" && s.outcome !== "skipped")
                .length,
            },
          ])
          .catch((): [string, BotCounts] => [
            bot.name,
            { orders: 0, trades: 0, signals: 0, rejected: 0 },
          ]),
      ),
    ).then((entries) => {
      if (!cancelled) setCounts(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [accountId, symbol, activeBots]);

  async function activate(v: StrategyVersionSummary) {
    if (!accountId) return;
    setBusyKey(v.id);
    setError(null);
    setJustActivated(null);
    try {
      if (v.status !== "active") {
        await activateStrategyVersion(accountId, v.id);
      }
      const result = await addBotToSymbol(symbol, v.name);
      if (result.newly_activated) {
        setJustActivated(v.name);
      }
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "failed to activate this bot on " + symbol);
    } finally {
      setBusyKey(null);
    }
  }

  async function stop(botName: string) {
    setBusyKey(botName);
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

  const routedFamilies = new Set((activeBots ?? []).map((a) => a.strategy));
  const others = (candidates ?? []).filter((v) => !routedFamilies.has(v.name));

  const needle = filter.trim().toLowerCase();
  const filteredActiveBots = (activeBots ?? []).filter(
    (bot) =>
      needle === "" ||
      bot.bot_name.toLowerCase().includes(needle) ||
      bot.strategy.toLowerCase().includes(needle),
  );
  const filteredOthers = others.filter(
    (v) => needle === "" || v.name.toLowerCase().includes(needle),
  );

  return (
    <div className="flex flex-col gap-2 text-sm">
      {justActivated && (
        <p className="rounded border border-sell bg-sell/10 px-2 py-1 text-xs text-sell">
          {symbol} is now live-trading with {justActivated} — newly activated, not just added.
        </p>
      )}
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter bots by name…"
        className="rounded border border-line bg-transparent px-2 py-1 text-xs placeholder:text-ink-muted focus:border-accent focus:outline-none"
      />
      <div>
        {activeBots === null ? (
          <span className="text-ink-muted">Loading bot assignments for {symbol}…</span>
        ) : activeBots.length === 0 ? (
          <span className="text-ink-muted">No bot active on {symbol}.</span>
        ) : filteredActiveBots.length === 0 ? (
          <span className="text-ink-muted">No active bots match &ldquo;{filter}&rdquo;.</span>
        ) : (
          <ul className="flex flex-col gap-1">
            {filteredActiveBots.map((bot) => {
              const version = (candidates ?? []).find(
                (v) => v.name === bot.strategy && v.status === "active",
              );
              const botCounts = counts[bot.name];
              return (
                <li key={bot.bot_name} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      {version ? (
                        <Link
                          href={`/strategies/versions/${version.id}`}
                          className="text-accent hover:underline"
                        >
                          {bot.bot_name}: {version.name} v{version.version}
                        </Link>
                      ) : (
                        <span className="text-ink-muted">
                          {bot.bot_name}: &ldquo;{bot.strategy}&rdquo;, no active version
                        </span>
                      )}
                    </span>
                    <button
                      type="button"
                      className={`shrink-0 cursor-pointer rounded border p-1 disabled:opacity-40 disabled:cursor-not-allowed ${
                        activeSignalsSkill === bot.name
                          ? "border-accent text-accent bg-accent/10"
                          : "border-line text-ink-muted hover:text-accent hover:border-accent"
                      }`}
                      onClick={() => onToggleSignals?.(bot.name)}
                      disabled={signalsDisabled}
                      title={
                        signalsDisabled
                          ? "Exit the backtest view to inspect a live bot's signals"
                          : activeSignalsSkill === bot.name
                            ? `Hide ${bot.bot_name}'s signals, trades, and indicators`
                            : `Show ${bot.bot_name}'s signal history, closed positions, and indicators used`
                      }
                    >
                      {activeSignalsSkill === bot.name ? <EyeOff size={13} /> : <Eye size={13} />}
                    </button>
                    <button
                      type="button"
                      className="shrink-0 cursor-pointer rounded border border-err px-2 py-0.5 text-xs text-err hover:bg-err hover:text-bg disabled:opacity-50"
                      onClick={() => stop(bot.bot_name)}
                      disabled={busyKey !== null}
                    >
                      {busyKey === bot.bot_name ? "Stopping…" : "Stop"}
                    </button>
                  </div>
                  <div className="flex items-center gap-1">
                    <CountChip label="Sig" count={botCounts?.signals} title="Signals seen (opened + vetoed/rejected)" />
                    <CountChip label="Rej" count={botCounts?.rejected} title="Signals vetoed/rejected (not opened as a trade)" />
                    <CountChip label="Ord" count={botCounts?.orders} title="Orders placed (open + closed)" />
                    <CountChip label="Trd" count={botCounts?.trades} title="Closed trades" />
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {candidates === null ? (
        <p className="text-xs text-ink-muted">Loading bots for {symbol}…</p>
      ) : filteredOthers.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {filteredOthers.map((v) => (
            <li key={v.id} className="flex items-center justify-between gap-2">
              <Link
                href={`/strategies/versions/${v.id}`}
                className="truncate text-ink-muted hover:text-accent hover:underline"
                title={`${v.name} v${v.version}`}
              >
                {v.name} v{v.version}
                {v.status === "active" && <span className="ml-1 text-xs text-ok">(active)</span>}
              </Link>
              <button
                type="button"
                className="shrink-0 cursor-pointer rounded border border-accent px-2 py-0.5 text-xs text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
                onClick={() => activate(v)}
                disabled={busyKey !== null}
              >
                {busyKey === v.id ? "Activating…" : "Activate on " + symbol}
              </button>
            </li>
          ))}
        </ul>
      ) : others.length > 0 ? (
        <p className="text-xs text-ink-muted">No other bots match &ldquo;{filter}&rdquo;.</p>
      ) : (
        <p className="text-xs text-ink-muted">No other validated bots for {symbol} yet.</p>
      )}
      {error && <p className="text-xs text-err">{error}</p>}
      <Link
        href={`/bots?symbol=${encodeURIComponent(symbol)}`}
        className="text-accent hover:underline"
      >
        + Generate a new bot for {symbol}
      </Link>
    </div>
  );
}

function CountChip({ label, count, title }: { label: string; count: number | undefined; title: string }) {
  return (
    <span
      className="rounded-full border border-line px-1.5 py-0.5 text-[10px] whitespace-nowrap text-ink-muted"
      title={title}
    >
      {label} {count ?? "…"}
    </span>
  );
}
