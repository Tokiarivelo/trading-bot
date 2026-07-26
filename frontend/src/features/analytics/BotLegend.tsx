"use client";

import { money } from "./format";
import type { ChartedBot } from "./chartTooltip";

/** One legend, shared above all three stacked charts (equity/P&L/drawdown)
 * — they all plot the same bot set in the same fixed colors, so repeating
 * a legend per chart would just be noise. */
export function BotLegend({ bots }: { bots: ChartedBot[] }) {
  if (bots.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-line px-3 py-2 text-xs">
      {bots.map((bot) => (
        <span key={bot.skill} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: bot.color }} />
          <span className="text-ink">{bot.bot_name}</span>
          <span className={bot.total_profit >= 0 ? "text-ok" : "text-err"}>
            {money(bot.total_profit, { sign: true })}
          </span>
        </span>
      ))}
    </div>
  );
}
