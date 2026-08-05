"use client";

import type { BotAnalytics } from "@/shared/api/client";
import { useSortableRows } from "@/shared/hooks/useSortableRows";
import { SortTh } from "@/shared/ui/SortTh";
import { duration, money, pct, plTone, profitFactor, timeAgo } from "./format";

type SortKey =
  | "bot_name"
  | "symbol"
  | "trade_count"
  | "win_rate"
  | "profit_factor"
  | "total_profit"
  | "expectancy"
  | "max_drawdown"
  | "avg_trade_duration_seconds"
  | "last_trade_time";

function sortValue(row: BotAnalytics, key: SortKey): string | number | null {
  return row[key];
}

/** Ranks bots by realized performance — the table the user reads to decide
 * which strategy/approach is actually working. Checkboxes control which
 * bots' equity curves are overlaid on `BotEquityChart` above. */
export function BotPerformanceTable({
  bots,
  selected,
  onToggle,
  atCapacity = false,
  maxCharted,
}: {
  bots: BotAnalytics[];
  selected: Set<string>;
  onToggle: (skill: string) => void;
  /** True when the chart already holds `maxCharted` bots — unchecked boxes are
   * then disabled so the cap reads as a limit rather than a broken checkbox. */
  atCapacity?: boolean;
  maxCharted?: number;
}) {
  const { sorted, sort, toggle } = useSortableRows<BotAnalytics, SortKey>(bots, sortValue, {
    key: "total_profit",
    dir: "desc",
  });

  if (bots.length === 0) {
    return (
      <p className="p-4 text-sm text-ink-muted">
        No bot-attributed trades yet — trades placed manually or via the API don&apos;t count
        toward a bot&apos;s record.
      </p>
    );
  }

  const bestSkill = bots.length > 0 ? bots.reduce((a, b) => (b.total_profit > a.total_profit ? b : a)).skill : null;
  const worstSkill =
    bots.length > 1 ? bots.reduce((a, b) => (b.total_profit < a.total_profit ? b : a)).skill : null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1100px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-muted">
            <th className="px-3 py-2 font-medium">Chart</th>
            <SortTh className="px-3 py-2 font-medium" label="Bot" sortKey="bot_name" sort={sort} onSort={toggle} />
            <SortTh className="px-3 py-2 font-medium" label="Symbol" sortKey="symbol" sort={sort} onSort={toggle} />
            <SortTh className="px-3 py-2 font-medium" label="Trades" sortKey="trade_count" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Win rate" sortKey="win_rate" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Profit factor" sortKey="profit_factor" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Total P/L" sortKey="total_profit" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Expectancy" sortKey="expectancy" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Max drawdown" sortKey="max_drawdown" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Avg duration" sortKey="avg_trade_duration_seconds" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Last trade" sortKey="last_trade_time" sort={sort} onSort={toggle} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((b) => (
            <tr
              key={b.skill}
              className={`border-b border-line last:border-0 hover:bg-panel/40 ${
                selected.has(b.skill) ? "bg-accent/5" : ""
              }`}
            >
              <Td>
                <input
                  type="checkbox"
                  checked={selected.has(b.skill)}
                  onChange={() => onToggle(b.skill)}
                  disabled={atCapacity && !selected.has(b.skill)}
                  title={
                    atCapacity && !selected.has(b.skill)
                      ? `Chart is full (${maxCharted} bots) — uncheck one first`
                      : undefined
                  }
                  className="cursor-pointer accent-accent disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={`Show ${b.bot_name} equity curve`}
                />
              </Td>
              <Td className="font-medium text-ink">
                <div className="flex items-center gap-1.5">
                  {b.bot_name}
                  {b.skill === bestSkill && (
                    <span
                      className="rounded bg-ok/15 px-1.5 py-0.5 text-2xs font-semibold text-ok"
                      title="Highest total P/L among all bots"
                    >
                      Best
                    </span>
                  )}
                  {b.skill === worstSkill && (
                    <span
                      className="rounded bg-err/15 px-1.5 py-0.5 text-2xs font-semibold text-err"
                      title="Lowest total P/L among all bots"
                    >
                      Worst
                    </span>
                  )}
                </div>
                <div className="text-xs text-ink-muted">{b.strategy_version ?? "—"}</div>
              </Td>
              <Td>{b.symbol}</Td>
              <Td align="right">
                {b.trade_count}
                {b.open_count > 0 && (
                  <span className="ml-1 text-xs text-ink-muted">({b.open_count} open)</span>
                )}
              </Td>
              <Td align="right">{b.closed_count > 0 ? pct(b.win_rate) : "—"}</Td>
              <Td align="right">{profitFactor(b.profit_factor)}</Td>
              <Td align="right" className={plTone(b.total_profit)}>
                {money(b.total_profit, { sign: true })}
              </Td>
              <Td align="right" className={plTone(b.expectancy)}>
                {b.closed_count > 0 ? money(b.expectancy, { sign: true }) : "—"}
              </Td>
              <Td align="right" className="text-err">
                {b.max_drawdown > 0 ? `-${money(b.max_drawdown)}` : "—"}
              </Td>
              <Td align="right">{duration(b.avg_trade_duration_seconds)}</Td>
              <Td className="text-ink-muted">{timeAgo(b.last_trade_time)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
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
