"use client";

/**
 * Polls the active strategy versions and resolves the one (if any) whose
 * spec targets `symbol` — used by the dashboard to know which PDF-derived
 * indicators/price levels to overlay on `ChartPanel` for the symbol being
 * viewed. Null when no AI-generated strategy is active for that symbol.
 */

import { useEffect, useRef, useState } from "react";
import { getStrategyVersions, type StrategyVersionSummary } from "@/shared/api/client";

const POLL_MS = 5000;

export function useActiveStrategyForSymbol(symbol: string): StrategyVersionSummary | null {
  const [activeStrategy, setActiveStrategy] = useState<StrategyVersionSummary | null>(null);
  const symbolRef = useRef(symbol);
  symbolRef.current = symbol;

  useEffect(() => {
    let cancelled = false;

    const refresh = () => {
      getStrategyVersions(undefined, "active")
        .then((versions) => {
          if (cancelled) return;
          const match =
            versions.find((v) => v.spec?.symbols.includes(symbolRef.current)) ?? null;
          setActiveStrategy(match);
        })
        .catch(() => {});
    };

    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol]);

  return activeStrategy;
}
