"use client";

import { useMemo, useState } from "react";
import { MenuButton } from "@/shared/ui/NavigationDrawer";
import { AnalyticsOverview } from "./AnalyticsOverview";
import { BotDrawdownChart } from "./BotDrawdownChart";
import { BotEquityChart, seriesColor } from "./BotEquityChart";
import { BotLegend } from "./BotLegend";
import { BotPerformanceTable } from "./BotPerformanceTable";
import { SymbolAnalyticsTable } from "./SymbolAnalyticsTable";
import { TradePnLHistogram } from "./TradePnLHistogram";
import { useAnalytics } from "./useAnalytics";

const MAX_CHARTED_BOTS = 6;
const DEFAULT_CHARTED_BOTS = 3;

export function AnalyticsPage() {
  const { symbols, bots, loading, error, refresh } = useAnalytics();
  const [selected, setSelected] = useState<Set<string> | null>(null);

  // Bots are already sorted by total_profit desc from the API; keep that
  // order fixed so a bot's chart color never changes as checkboxes toggle.
  const rankedBots = useMemo(() => bots.map((b, i) => ({ ...b, color: seriesColor(i) })), [bots]);

  const activeSelection =
    selected ?? new Set(rankedBots.slice(0, DEFAULT_CHARTED_BOTS).map((b) => b.skill));

  function toggle(skill: string) {
    const next = new Set(activeSelection);
    if (next.has(skill)) {
      next.delete(skill);
    } else {
      if (next.size >= MAX_CHARTED_BOTS) return;
      next.add(skill);
    }
    setSelected(next);
  }

  const chartedBots = rankedBots.filter((b) => activeSelection.has(b.skill));

  return (
    <div className="flex h-screen flex-col bg-bg text-ink">
      <header className="flex items-center gap-3 border-b border-line px-6 py-3 bg-panel/30 backdrop-blur-md">
        <MenuButton />
        <div className="flex flex-col">
          <h1 className="text-lg font-bold tracking-wide text-ink">Analytics</h1>
          <p className="text-3xs font-semibold uppercase tracking-wider text-ink-muted">
            Symbols &amp; Bot Performance
          </p>
        </div>
        <button
          onClick={refresh}
          title="Refresh data"
          className="ml-auto cursor-pointer rounded-lg border border-line bg-panel p-1.5 text-ink-muted transition-all duration-200 hover:bg-bg hover:text-ink"
        >
          <svg className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10H18.228" />
          </svg>
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6 space-y-6">
        {error && <p className="text-sm text-err">{error}</p>}
        {loading && symbols.length === 0 && bots.length === 0 ? (
          <p className="text-sm text-ink-muted">Loading analytics…</p>
        ) : (
          <>
            <AnalyticsOverview symbols={symbols} bots={bots} />

            <section className="rounded-xl border border-line bg-panel/30 shadow-inner overflow-hidden">
              <header className="border-b border-line px-4 py-2.5">
                <h2 className="text-sm font-bold text-ink">Bot comparison charts</h2>
                <p className="text-xs text-ink-muted">
                  Check bots in the table below to overlay them here — up to {MAX_CHARTED_BOTS} at once, in a
                  fixed color per bot across all three charts.
                </p>
              </header>
              <BotLegend bots={chartedBots} />

              <div className="border-b border-line px-4 pt-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Equity curve — cumulative realized profit
              </div>
              <BotEquityChart bots={chartedBots} />

              <div className="border-y border-line px-4 pt-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Trade P/L — per-trade wins/losses over time
              </div>
              <TradePnLHistogram bots={chartedBots} />

              <div className="border-y border-line px-4 pt-3 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                Drawdown — distance below running peak
              </div>
              <BotDrawdownChart bots={chartedBots} />
            </section>

            <section className="rounded-xl border border-line bg-panel/30 shadow-inner overflow-hidden">
              <header className="border-b border-line px-4 py-2.5">
                <h2 className="text-sm font-bold text-ink">Bot performance</h2>
                <p className="text-xs text-ink-muted">
                  Every bot ranked by realized profit — check the box to overlay its equity curve above.
                </p>
              </header>
              <BotPerformanceTable bots={bots} selected={activeSelection} onToggle={toggle} />
            </section>

            <section className="rounded-xl border border-line bg-panel/30 shadow-inner overflow-hidden">
              <header className="border-b border-line px-4 py-2.5">
                <h2 className="text-sm font-bold text-ink">Symbols traded</h2>
                <p className="text-xs text-ink-muted">
                  Every trade on each symbol, any bot or manual — which instruments are actually profitable.
                </p>
              </header>
              <SymbolAnalyticsTable symbols={symbols} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
