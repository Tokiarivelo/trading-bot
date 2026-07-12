import type { TradeHistoryItem, TradeOutcome } from "@/shared/api/client";

export type GroupBy = "none" | "symbol" | "date" | "side" | "strategy_version" | "skill" | "outcome";

export interface TradeGroup {
  key: string;
  label: string;
  trades: TradeHistoryItem[];
  count: number;
  closedCount: number;
  netProfit: number;
  winRate: number | null; // null when no closed trades in the group
}

export function outcomeOf(trade: TradeHistoryItem): TradeOutcome {
  if (trade.close_time === null || trade.profit === null) return "open";
  if (trade.profit > 0) return "win";
  if (trade.profit < 0) return "loss";
  return "breakeven";
}

function keyFor(trade: TradeHistoryItem, groupBy: GroupBy): { key: string; label: string } {
  switch (groupBy) {
    case "symbol":
      return { key: trade.symbol, label: trade.symbol };
    case "date": {
      const day = new Date(trade.open_time * 1000).toISOString().slice(0, 10);
      return { key: day, label: day };
    }
    case "side":
      return { key: trade.side, label: trade.side === "buy" ? "Buy" : "Sell" };
    case "strategy_version": {
      const v = trade.strategy_version ?? "(manual / unknown)";
      return { key: v, label: v };
    }
    case "skill": {
      const s = trade.skill ?? "(none)";
      return { key: s, label: s };
    }
    case "outcome": {
      const o = outcomeOf(trade);
      return { key: o, label: o[0].toUpperCase() + o.slice(1) };
    }
    case "none":
    default:
      return { key: "all", label: "All trades" };
  }
}

/** Groups the current page of trades by the chosen field and computes
 * per-group aggregates (net P/L, win rate over closed trades). Grouping is
 * client-side over whatever page is loaded — it categorizes what's on
 * screen, it doesn't re-query the server. */
export function groupTrades(trades: TradeHistoryItem[], groupBy: GroupBy): TradeGroup[] {
  const groups = new Map<string, TradeGroup>();
  for (const trade of trades) {
    const { key, label } = keyFor(trade, groupBy);
    let group = groups.get(key);
    if (!group) {
      group = { key, label, trades: [], count: 0, closedCount: 0, netProfit: 0, winRate: null };
      groups.set(key, group);
    }
    group.trades.push(trade);
    group.count += 1;
    if (trade.profit !== null) {
      group.netProfit += trade.profit;
    }
    if (outcomeOf(trade) !== "open") {
      group.closedCount += 1;
    }
  }
  for (const group of groups.values()) {
    const wins = group.trades.filter((t) => outcomeOf(t) === "win").length;
    group.winRate = group.closedCount > 0 ? wins / group.closedCount : null;
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
}
