"use client";

import type { BotAnalytics, SymbolAnalytics } from "@/shared/api/client";
import { money, pct, plTone, profitFactor } from "./format";

function StatTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "err";
}) {
  const valueCls = tone === "ok" ? "text-ok" : tone === "err" ? "text-err" : "text-ink";
  return (
    <div className="rounded-xl border border-line bg-panel/60 p-4 shadow-sm backdrop-blur-md">
      <div className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">{label}</div>
      <div className={`mt-1 text-xl font-extrabold ${valueCls}`}>{value}</div>
    </div>
  );
}

/** Top-level KPI strip + a "best approach" callout — bots need at least a
 * handful of closed trades before profit factor/win rate are meaningful, so
 * the callout is scoped to bots with >= `MIN_TRADES_FOR_CALLOUT` closed
 * trades rather than whichever bot happens to have the highest ratio off one
 * lucky trade. */
const MIN_TRADES_FOR_CALLOUT = 5;

export function AnalyticsOverview({ symbols, bots }: { symbols: SymbolAnalytics[]; bots: BotAnalytics[] }) {
  const totalTrades = symbols.reduce((sum, s) => sum + s.trade_count, 0);
  const totalClosed = symbols.reduce((sum, s) => sum + s.closed_count, 0);
  const totalWins = symbols.reduce((sum, s) => sum + s.win_count, 0);
  const totalProfit = symbols.reduce((sum, s) => sum + s.total_profit, 0);
  const overallWinRate = totalClosed > 0 ? totalWins / totalClosed : 0;

  const bestByProfit = bots.length > 0 ? bots.reduce((a, b) => (b.total_profit > a.total_profit ? b : a)) : null;

  const eligible = bots.filter((b) => b.closed_count >= MIN_TRADES_FOR_CALLOUT);
  const bestApproach =
    eligible.length > 0
      ? eligible.reduce((a, b) => {
          // profit_factor is null only when a bot has no losing trades yet —
          // treat that as a strong (capped) ratio rather than undefined, so
          // a spotless-but-small sample doesn't win purely on a null check.
          const PF_CAP_WHEN_NO_LOSSES = 5;
          const scoreA = (a.profit_factor ?? PF_CAP_WHEN_NO_LOSSES) * a.win_rate;
          const scoreB = (b.profit_factor ?? PF_CAP_WHEN_NO_LOSSES) * b.win_rate;
          return scoreB > scoreA ? b : a;
        })
      : null;

  return (
    <div className="flex flex-col gap-4">
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Symbols traded" value={String(symbols.length)} />
        <StatTile label="Bots tracked" value={String(bots.length)} />
        <StatTile label="Total trades" value={String(totalTrades)} />
        <StatTile label="Overall win rate" value={totalClosed > 0 ? pct(overallWinRate) : "—"} />
        <StatTile
          label="Total realized P/L"
          value={money(totalProfit, { sign: true })}
          tone={totalProfit >= 0 ? "ok" : "err"}
        />
        <StatTile
          label="Top bot P/L"
          value={bestByProfit ? money(bestByProfit.total_profit, { sign: true }) : "—"}
          tone={bestByProfit && bestByProfit.total_profit >= 0 ? "ok" : "neutral"}
        />
      </section>

      {bestApproach && (
        <section className="rounded-xl border border-accent/40 bg-accent/5 p-4">
          <div className="text-2xs font-semibold uppercase tracking-wider text-accent">
            Best approach right now
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-ink">{bestApproach.bot_name}</span>
            <span className="text-sm text-ink-muted">
              {bestApproach.symbol} · {bestApproach.strategy_version ?? "unknown strategy"}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            {pct(bestApproach.win_rate)} win rate over {bestApproach.closed_count} closed trades, profit factor{" "}
            {profitFactor(bestApproach.profit_factor)}, total{" "}
            <span className={plTone(bestApproach.total_profit)}>
              {money(bestApproach.total_profit, { sign: true })}
            </span>
            . Ranked by win rate × profit factor among bots with {MIN_TRADES_FOR_CALLOUT}+ closed trades — not
            necessarily the highest total P/L, which may just reflect more trades or larger size.
          </p>
        </section>
      )}
    </div>
  );
}
