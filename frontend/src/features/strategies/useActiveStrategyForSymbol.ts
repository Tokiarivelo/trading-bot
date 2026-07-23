"use client";

/**
 * Polls the active strategy versions and resolves the one (if any) whose
 * spec targets `symbol` — used by the dashboard to know which PDF-derived
 * indicators/price levels to overlay on `ChartPanel` for the symbol being
 * viewed. Null when no AI-generated strategy is active for that symbol.
 */

import { useEffect, useRef, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import { getStrategyVersions, type StrategyVersionSummary } from "@/shared/api/client";

const POLL_MS = 5000;

/** Whether `a` and `b` are the same strategy version for the purposes of
 * anything that reacts to `activeStrategy` changing (chart re-plots) — not a
 * deep-equal, just the fields that actually change when the active strategy
 * genuinely changes (a new/edited/(de)activated version), so polling the
 * same unchanged version doesn't hand out a new object reference. */
function sameStrategyVersion(
  a: StrategyVersionSummary | null,
  b: StrategyVersionSummary | null,
): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return (
    a.id === b.id &&
    a.code_hash === b.code_hash &&
    a.status === b.status &&
    a.paused === b.paused
  );
}

export function useActiveStrategyForSymbol(symbol: string): StrategyVersionSummary | null {
  const accountId = useActiveAccount();
  const [activeStrategy, setActiveStrategy] = useState<StrategyVersionSummary | null>(null);
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  useEffect(() => {
    if (!accountId) return;
    let cancelled = false;

    const refresh = () => {
      getStrategyVersions(accountId, undefined, "active")
        .then((versions) => {
          if (cancelled) return;
          const match =
            versions.find((v) => v.spec?.symbols.includes(symbolRef.current)) ?? null;
          // Keep the previous object reference when nothing meaningful
          // changed — otherwise every poll (every 5s, for the life of the
          // chart) hands consumers (ChartPanel's indicator/drawing rebuild
          // effect) a "new" activeStrategy and triggers a full teardown and
          // recompute for no reason.
          setActiveStrategy((prev) =>
            sameStrategyVersion(prev, match) ? prev : match,
          );
        })
        .catch(() => {});
    };

    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accountId, symbol]);

  return activeStrategy;
}
