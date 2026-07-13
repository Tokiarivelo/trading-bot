"use client";

/**
 * Chart-page bot picker for the active symbol (§5/§6.5, §6.6): shows which
 * bot is actually routed to trade this symbol live — read from the skill
 * assignment (skills/normal/<symbol>.yaml via GET /skills/normal), not just
 * "some active version whose spec happens to list this symbol" — and lets
 * the trader apply any other validated/active bot to it.
 *
 * Applying a bot from a *different* family than what's currently routed
 * both activates that family's version (if it isn't already the live one)
 * and reassigns the symbol's routing via assignStrategyToSymbol — activating
 * alone only swaps versions within an already-routed family and silently
 * does nothing to reroute a symbol to a different family.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  activateStrategyVersion,
  assignStrategyToSymbol,
  getSkillAssignments,
  getStrategyVersions,
  type StrategyVersionSummary,
} from "@/shared/api/client";

export function BotSelector({ symbol }: { symbol: string }) {
  const [candidates, setCandidates] = useState<StrategyVersionSummary[] | null>(null);
  const [routedFamily, setRoutedFamily] = useState<string | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([getStrategyVersions(), getSkillAssignments()])
      .then(([versions, assignments]) => {
        setCandidates(
          versions
            .filter((v) => v.status !== "archived" && (v.spec?.symbols ?? []).includes(symbol))
            .sort((a, b) => b.created_at - a.created_at),
        );
        setRoutedFamily(assignments.find((a) => a.symbol === symbol)?.strategy ?? null);
      })
      .catch(() => setError("failed to load bots for this symbol"));
  }, [symbol]);

  useEffect(() => {
    setCandidates(null);
    setRoutedFamily(undefined);
    refresh();
  }, [refresh]);

  const routedVersion =
    (candidates ?? []).find((v) => v.name === routedFamily && v.status === "active") ?? null;

  async function apply(v: StrategyVersionSummary) {
    setBusyId(v.id);
    setError(null);
    try {
      if (v.status !== "active") {
        await activateStrategyVersion(v.id);
      }
      await assignStrategyToSymbol(symbol, v.name);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "failed to apply this bot to " + symbol);
    } finally {
      setBusyId(null);
    }
  }

  const others = (candidates ?? []).filter((v) => v.id !== routedVersion?.id);

  return (
    <div className="flex flex-col gap-2 text-sm">
      <div>
        {routedFamily === undefined ? (
          <span className="text-ink-muted">Loading bot assignment for {symbol}…</span>
        ) : routedVersion ? (
          <>
            Bot running on {symbol}:{" "}
            <Link
              href={`/strategies/versions/${routedVersion.id}`}
              className="text-accent hover:underline"
            >
              {routedVersion.name} v{routedVersion.version}
            </Link>
          </>
        ) : routedFamily ? (
          <span className="text-ink-muted">
            {symbol} is routed to &ldquo;{routedFamily}&rdquo;, which has no active version.
          </span>
        ) : (
          <span className="text-ink-muted">No bot active on {symbol}.</span>
        )}
      </div>
      {candidates === null ? (
        <p className="text-xs text-ink-muted">Loading bots for {symbol}…</p>
      ) : others.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {others.map((v) => (
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
                onClick={() => apply(v)}
                disabled={busyId !== null}
              >
                {busyId === v.id ? "Applying…" : "Apply to " + symbol}
              </button>
            </li>
          ))}
        </ul>
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
