"use client";

/**
 * The real "apply a bot to a symbol" control (§6.6): shows every configured
 * symbol's current live strategy assignment (skills/normal/<symbol>.yaml,
 * what TradeEngine._try_enter actually reads via SkillSelector) and lets the
 * trader reroute it to any other currently-active bot family. Reassigning
 * here writes the YAML and hot-swaps the live selector immediately — no
 * restart needed.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  assignStrategyToSymbol,
  getSkillAssignments,
  getStrategyVersions,
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
    return <p className="p-4 text-sm text-ink-muted">Loading symbol assignments…</p>;
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {error && <p className="text-sm text-err">{error}</p>}
      {assignments.length === 0 ? (
        <p className="text-sm text-ink-muted">No symbols configured yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-panel">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-muted">
                <th className="px-3 py-2 font-medium">Symbol</th>
                <th className="px-3 py-2 font-medium">Bot trading it live</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.symbol} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-medium">{a.symbol}</td>
                  <td className="px-3 py-2">
                    <select
                      className="rounded border border-line bg-bg px-2 py-1 text-sm text-ink disabled:opacity-50"
                      value={a.strategy}
                      disabled={busySymbol !== null}
                      onChange={(e) => reassign(a.symbol, e.target.value)}
                    >
                      {!activeBots.includes(a.strategy) && (
                        <option value={a.strategy}>{a.strategy} (not currently active)</option>
                      )}
                      {activeBots.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                    {busySymbol === a.symbol && (
                      <span className="ml-2 text-xs text-ink-muted">Applying…</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
