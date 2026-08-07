"use client";

import { useMemo, useState } from "react";
import type { RegimeAnalytics } from "@/shared/api/client";
import { useSortableRows } from "@/shared/hooks/useSortableRows";
import { SortTh } from "@/shared/ui/SortTh";
import { money, pct, plTone, profitFactor } from "./format";
import type { RegimeAnalyticsSortKey, RegimeDimension } from "./types";

const DIMENSION_TABS: { key: RegimeDimension; label: string; hint: string }[] = [
  {
    key: "volatility",
    label: "Volatility",
    hint: "ATR-percentile bucket at entry: low / normal / high / extreme.",
  },
  {
    key: "trend",
    label: "Trend",
    hint: "ADX-based classification at entry: trending vs ranging.",
  },
  {
    key: "session",
    label: "Session",
    hint: "Trading session (UTC hour) at entry: asian / london / overlap / new_york / off_session.",
  },
];

function sortValue(row: RegimeAnalytics, key: RegimeAnalyticsSortKey): string | number | null {
  return row[key];
}

interface RegimeAnalyticsPanelProps {
  regimes: RegimeAnalytics[];
  loading: boolean;
  error: string | null;
}

/** Splits each bot's win rate / profit factor / expectancy by the market
 * regime it traded in at entry (OBSERVABILITY_PLAN.md Phase 6) — one tab per
 * dimension (volatility / trend / session), each a sortable table of every
 * (bot, bucket) combination with at least one attributable trade. Answers
 * "is this bot's edge regime-dependent" (e.g. only profitable while
 * trending, or only during the London/NY overlap) — a narrower slice than
 * `BotPerformanceTable`'s overall numbers, which this panel sits alongside. */
export function RegimeAnalyticsPanel({ regimes, loading, error }: RegimeAnalyticsPanelProps) {
  const [dimension, setDimension] = useState<RegimeDimension>("volatility");

  const rows = useMemo(
    () => regimes.filter((r) => r.dimension === dimension),
    [regimes, dimension],
  );

  const { sorted, sort, toggle } = useSortableRows<RegimeAnalytics, RegimeAnalyticsSortKey>(
    rows,
    sortValue,
    { key: "total_profit", dir: "desc" },
  );

  let content: React.ReactNode;
  if (error) {
    content = <p className="p-4 text-sm text-err">{error}</p>;
  } else if (loading && regimes.length === 0) {
    content = <p className="p-4 text-sm text-ink-muted">Loading regime analytics…</p>;
  } else if (sorted.length === 0) {
    content = (
      <p className="p-4 text-sm text-ink-muted">
        No closed, regime-tagged trades yet for this dimension — trades journaled before regime
        tagging landed, or whose entry timeframe had no candles to classify, carry no tag and are
        excluded here rather than shown under a fabricated &quot;unknown&quot; bucket.
      </p>
    );
  } else {
    content = (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-muted">
              <SortTh className="px-3 py-2 font-medium" label="Bot" sortKey="bot_name" sort={sort} onSort={toggle} />
              <SortTh className="px-3 py-2 font-medium" label="Bucket" sortKey="bucket" sort={sort} onSort={toggle} />
              <SortTh className="px-3 py-2 font-medium" label="Trades" sortKey="trade_count" sort={sort} onSort={toggle} align="right" />
              <SortTh className="px-3 py-2 font-medium" label="Win rate" sortKey="win_rate" sort={sort} onSort={toggle} align="right" />
              <SortTh className="px-3 py-2 font-medium" label="Profit factor" sortKey="profit_factor" sort={sort} onSort={toggle} align="right" />
              <SortTh className="px-3 py-2 font-medium" label="Expectancy" sortKey="expectancy" sort={sort} onSort={toggle} align="right" />
              <SortTh className="px-3 py-2 font-medium" label="Total P/L" sortKey="total_profit" sort={sort} onSort={toggle} align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={`${r.skill}:${r.dimension}:${r.bucket}`}
                className="border-b border-line last:border-0 hover:bg-panel/40"
              >
                <Td className="font-medium text-ink">{r.bot_name}</Td>
                <Td>
                  <span className="rounded bg-panel px-1.5 py-0.5 text-xs font-semibold text-ink-muted">
                    {r.bucket}
                  </span>
                </Td>
                <Td align="right">{r.trade_count}</Td>
                <Td align="right">{r.closed_count > 0 ? pct(r.win_rate) : "—"}</Td>
                <Td align="right">{profitFactor(r.profit_factor)}</Td>
                <Td align="right" className={plTone(r.expectancy)}>
                  {r.closed_count > 0 ? money(r.expectancy, { sign: true }) : "—"}
                </Td>
                <Td align="right" className={plTone(r.total_profit)}>
                  {money(r.total_profit, { sign: true })}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div>
      <div className="flex gap-1 border-b border-line px-4 pt-2">
        {DIMENSION_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setDimension(tab.key)}
            title={tab.hint}
            className={`cursor-pointer rounded-t-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              dimension === tab.key
                ? "border border-b-0 border-line bg-panel text-ink"
                : "text-ink-muted hover:text-ink"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {content}
    </div>
  );
}

function Td({
  children,
  align = "left",
  className = "",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return <td className={`px-3 py-2 ${align === "right" ? "text-right" : ""} ${className}`}>{children}</td>;
}
