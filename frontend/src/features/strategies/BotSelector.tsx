"use client";

/**
 * Chart-page bot picker for the active symbol (§5/§6.5): shows which bot (if
 * any) is currently trading this symbol, lets the trader switch to any other
 * validated/active version scoped to it, or jump straight into generating a
 * brand-new strategy for it via the PDF pipeline.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  activateStrategyVersion,
  getStrategyVersions,
  type StrategyVersionSummary,
} from "@/shared/api/client";

export function BotSelector({
  symbol,
  activeStrategy,
}: {
  symbol: string;
  activeStrategy: StrategyVersionSummary | null;
}) {
  const [candidates, setCandidates] = useState<StrategyVersionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getStrategyVersions()
      .then((versions) => {
        setCandidates(
          versions
            .filter((v) => v.status !== "archived" && (v.spec?.symbols ?? []).includes(symbol))
            .sort((a, b) => b.created_at - a.created_at),
        );
      })
      .catch(() => setError("failed to load bots for this symbol"));
  }, [symbol]);

  useEffect(() => {
    setCandidates(null);
    refresh();
  }, [refresh]);

  async function activate(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await activateStrategyVersion(id);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "activation failed");
    } finally {
      setBusyId(null);
    }
  }

  const others = (candidates ?? []).filter((v) => v.id !== activeStrategy?.id);

  return (
    <div className="flex flex-col gap-2 text-sm">
      <div>
        {activeStrategy ? (
          <>
            Bot running on {symbol}:{" "}
            <Link
              href={`/strategies/versions/${activeStrategy.id}`}
              className="text-accent hover:underline"
            >
              {activeStrategy.name} v{activeStrategy.version}
            </Link>
          </>
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
                onClick={() => activate(v.id)}
                disabled={busyId !== null}
              >
                {busyId === v.id ? "Activating…" : "Activate"}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-muted">No other validated bots for {symbol} yet.</p>
      )}
      {error && <p className="text-xs text-err">{error}</p>}
      <Link
        href={`/strategies?symbol=${encodeURIComponent(symbol)}`}
        className="text-accent hover:underline"
      >
        + Generate a new strategy for {symbol}
      </Link>
    </div>
  );
}
