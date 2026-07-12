"use client";

import { useState } from "react";
import type { TradeHistoryItem } from "@/shared/api/client";
import { StatusBadge } from "@/features/strategies/StatusBadge";
import { type GroupBy, type TradeGroup, groupTrades, outcomeOf } from "./groupTrades";

export function TradeHistoryTable({
  trades,
  groupBy,
}: {
  trades: TradeHistoryItem[];
  groupBy: GroupBy;
}) {
  const groups = groupTrades(trades, groupBy);

  if (groupBy === "none") {
    return (
      <div className="overflow-x-auto p-4">
        <TradesTable trades={trades} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {groups.map((group) => (
        <GroupSection key={group.key} group={group} />
      ))}
    </div>
  );
}

function GroupSection({ group }: { group: TradeGroup }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="rounded border border-line">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-4 bg-panel px-3 py-2 text-left text-sm hover:bg-panel/60"
        onClick={() => setCollapsed((v) => !v)}
      >
        <span className="flex items-center gap-2 font-medium">
          <span className="text-ink-muted">{collapsed ? "▸" : "▾"}</span>
          {group.label}
          <span className="text-xs font-normal text-ink-muted">
            ({group.count} trade{group.count === 1 ? "" : "s"})
          </span>
        </span>
        <span className="flex items-center gap-4 text-xs text-ink-muted">
          {group.winRate !== null && <span>win rate {(group.winRate * 100).toFixed(0)}%</span>}
          <span className={group.netProfit >= 0 ? "text-ok" : "text-err"}>
            net {group.netProfit >= 0 ? "+" : ""}
            {group.netProfit.toFixed(2)}
          </span>
        </span>
      </button>
      {!collapsed && (
        <div className="overflow-x-auto">
          <TradesTable trades={group.trades} />
        </div>
      )}
    </div>
  );
}

function TradesTable({ trades }: { trades: TradeHistoryItem[] }) {
  if (trades.length === 0) {
    return <p className="px-3 py-2 text-sm text-ink-muted">No trades.</p>;
  }
  return (
    <table className="w-full min-w-[960px] border-collapse text-sm">
      <thead>
        <tr className="border-b border-line text-left text-xs text-ink-muted">
          <Th>Symbol</Th>
          <Th>Side</Th>
          <Th align="right">Volume</Th>
          <Th>Opened</Th>
          <Th>Closed</Th>
          <Th align="right">Open price</Th>
          <Th align="right">Close price</Th>
          <Th align="right">P/L</Th>
          <Th>Strategy</Th>
          <Th>Skill</Th>
          <Th>Outcome</Th>
        </tr>
      </thead>
      <tbody>
        {trades.map((t) => (
          <tr key={t.id} className="border-b border-line last:border-0 hover:bg-panel/40">
            <Td>{t.symbol}</Td>
            <Td className={t.side === "buy" ? "text-ok" : "text-err"}>{t.side}</Td>
            <Td align="right">{t.volume}</Td>
            <Td>{formatTime(t.open_time)}</Td>
            <Td>{t.close_time !== null ? formatTime(t.close_time) : "—"}</Td>
            <Td align="right">{t.open_price}</Td>
            <Td align="right">{t.close_price ?? "—"}</Td>
            <Td align="right" className={plTone(t.profit)}>
              {t.profit !== null ? t.profit.toFixed(2) : "—"}
            </Td>
            <Td className="text-ink-muted">{t.strategy_version ?? "—"}</Td>
            <Td className="text-ink-muted">{t.skill ?? "—"}</Td>
            <Td>
              <StatusBadge status={outcomeOf(t)} />
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function plTone(profit: number | null): string {
  if (profit === null) return "";
  return profit >= 0 ? "text-ok" : "text-err";
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th className={`px-3 py-2 font-medium ${align === "right" ? "text-right" : ""}`}>{children}</th>
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
  return (
    <td className={`px-3 py-2 ${align === "right" ? "text-right" : ""} ${className}`}>{children}</td>
  );
}
