"use client";

import { useCallback, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import type { BotAnalytics, SymbolAnalytics } from "@/shared/api/client";
import { downloadCsv, downloadJson } from "@/shared/utils/download";
import { buildAnalyticsExport, flattenTradesForCsv } from "./export";

/** Exports the currently filtered analytics (bots + their full trade
 * history) as JSON or CSV, for offline/AI analysis of what's working. Runs
 * one paginated `/journal/history` fetch per filtered bot, so it can take a
 * few seconds for bots with long histories — callers should show `exporting`. */
export function useAnalyticsExport(
  filteredSymbols: SymbolAnalytics[],
  filteredBots: BotAnalytics[],
  activeSymbolFilter: string[],
  activeBotFilter: string[],
  dateFrom: string = "",
  dateTo: string = "",
  openFrom?: number,
  openTo?: number,
) {
  const accountId = useActiveAccount();
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (format: "json" | "csv") => {
      if (!accountId || filteredBots.length === 0) return;
      setExporting(true);
      setError(null);
      try {
        const payload = await buildAnalyticsExport(
          accountId,
          filteredSymbols,
          filteredBots,
          activeSymbolFilter,
          activeBotFilter,
          dateFrom,
          dateTo,
          openFrom,
          openTo,
        );
        const stamp = new Date().toISOString().slice(0, 10);
        if (format === "json") {
          downloadJson(payload, `analytics_export_${stamp}.json`);
        } else {
          downloadCsv(flattenTradesForCsv(payload.bots), `analytics_trades_${stamp}.csv`);
        }
      } catch {
        setError("Failed to build export — try again.");
      } finally {
        setExporting(false);
      }
    },
    [accountId, filteredSymbols, filteredBots, activeSymbolFilter, activeBotFilter, dateFrom, dateTo, openFrom, openTo],
  );

  return {
    exportJson: () => run("json"),
    exportCsv: () => run("csv"),
    exporting,
    error,
    disabled: filteredBots.length === 0,
  };
}
