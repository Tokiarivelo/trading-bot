"use client";

import type { SymbolAnalytics } from "@/shared/api/client";
import { useSortableRows } from "@/shared/hooks/useSortableRows";
import { SortTh } from "@/shared/ui/SortTh";
import { money, pct, plTone, profitFactor, timeAgo } from "./format";

type SortKey =
  | "symbol"
  | "trade_count"
  | "win_rate"
  | "profit_factor"
  | "total_profit"
  | "avg_win"
  | "avg_loss"
  | "total_volume"
  | "bot_count"
  | "last_trade_time";

function sortValue(row: SymbolAnalytics, key: SortKey): string | number | null {
  return row[key];
}

/** Every trade on each symbol (any bot, or manual) — answers "which
 * instrument is actually making money," independent of which bot traded it. */
export function SymbolAnalyticsTable({ symbols }: { symbols: SymbolAnalytics[] }) {
  const { sorted, sort, toggle } = useSortableRows<SymbolAnalytics, SortKey>(
    symbols,
    sortValue,
    { key: "total_profit", dir: "desc" },
  );

  if (symbols.length === 0) {
    return <p className="p-4 text-sm text-ink-muted">No journaled trades yet.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-muted">
            <SortTh className="px-3 py-2 font-medium" label="Symbol" sortKey="symbol" sort={sort} onSort={toggle} />
            <SortTh className="px-3 py-2 font-medium" label="Trades" sortKey="trade_count" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Win rate" sortKey="win_rate" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Profit factor" sortKey="profit_factor" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Total P/L" sortKey="total_profit" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Avg win" sortKey="avg_win" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Avg loss" sortKey="avg_loss" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Volume" sortKey="total_volume" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Bots" sortKey="bot_count" sort={sort} onSort={toggle} align="right" />
            <SortTh className="px-3 py-2 font-medium" label="Last trade" sortKey="last_trade_time" sort={sort} onSort={toggle} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => (
            <tr key={s.symbol} className="border-b border-line last:border-0 hover:bg-panel/40">
              <Td className="font-medium text-ink">{s.symbol}</Td>
              <Td align="right">
                {s.trade_count}
                {s.open_count > 0 && (
                  <span className="ml-1 text-xs text-ink-muted">({s.open_count} open)</span>
                )}
              </Td>
              <Td align="right">{s.closed_count > 0 ? pct(s.win_rate) : "—"}</Td>
              <Td align="right">{profitFactor(s.profit_factor)}</Td>
              <Td align="right" className={plTone(s.total_profit)}>
                {money(s.total_profit, { sign: true })}
              </Td>
              <Td align="right" className="text-ok">
                {s.avg_win > 0 ? money(s.avg_win) : "—"}
              </Td>
              <Td align="right" className="text-err">
                {s.avg_loss > 0 ? `-${money(s.avg_loss)}` : "—"}
              </Td>
              <Td align="right">{s.total_volume.toFixed(2)}</Td>
              <Td align="right">{s.bot_count}</Td>
              <Td className="text-ink-muted">{timeAgo(s.last_trade_time)}</Td>
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
