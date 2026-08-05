"use client";

import type { BotAnalytics } from "@/shared/api/client";
import { useSortableRows } from "@/shared/hooks/useSortableRows";
import { SortTh } from "@/shared/ui/SortTh";
import {
  duration,
  millis,
  money,
  pct,
  plTone,
  priceDelta,
  profitFactor,
  slippageTone,
  timeAgo,
} from "./format";

/** MT5's "the deal went through" return code — every other code in a bot's
 * histogram is a refusal or a partial fill worth surfacing. */
const RETCODE_DONE = 10009;

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
  | "last_trade_time"
  | "avg_slippage"
  | "avg_execution_latency_ms"
  | "mfe_mae_ratio";

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
      <table className="w-full min-w-[1500px] border-collapse text-sm">
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
            <SortTh
              className="px-3 py-2 font-medium"
              label="Avg slippage"
              title="Average fill price minus the price the order asked for, in price units. Positive means the fills cost this bot."
              sortKey="avg_slippage"
              sort={sort}
              onSort={toggle}
              align="right"
            />
            <SortTh
              className="px-3 py-2 font-medium"
              label="Latency"
              title="Average time from the strategy emitting the signal to the broker acknowledging the fill."
              sortKey="avg_execution_latency_ms"
              sort={sort}
              onSort={toggle}
              align="right"
            />
            <SortTh
              className="px-3 py-2 font-medium"
              label="MFE / MAE"
              title="Average maximum favorable vs adverse excursion, in price units — how far trades run for this bot before they turn."
              sortKey="mfe_mae_ratio"
              sort={sort}
              onSort={toggle}
              align="right"
            />
            <th className="px-3 py-2 font-medium">Broker codes</th>
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
              <Td align="right" className={slippageTone(b.avg_slippage)}>
                <span
                  title={
                    b.avg_slippage === null
                      ? "No trade of this bot carries an execution measurement yet."
                      : `Averaged over ${b.measured_slippage_count} measured fill(s).`
                  }
                >
                  {priceDelta(b.avg_slippage, { sign: true })}
                </span>
              </Td>
              <Td align="right">{millis(b.avg_execution_latency_ms)}</Td>
              <Td align="right">
                <ExcursionCell bot={b} />
              </Td>
              <Td>
                <RetcodeBadges codes={b.retcode_histogram} />
              </Td>
              <Td className="text-ink-muted">{timeAgo(b.last_trade_time)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Average favorable vs adverse excursion, with the diagnosis those two
 * numbers exist to support spelled out on hover: a loser that ran far into
 * profit first means the take-profit is out of reach, a winner that took
 * heat close to its stop means the stop has no room left. */
function ExcursionCell({ bot }: { bot: BotAnalytics }) {
  if (bot.avg_mfe === null && bot.avg_mae === null) {
    return <span className="text-ink-muted">—</span>;
  }
  const hints = [
    bot.avg_mfe_on_losers !== null &&
      `Losers ran ${priceDelta(bot.avg_mfe_on_losers)} into profit before turning — well above the average win means the take-profit sits past where price actually turns.`,
    bot.avg_mae_on_winners !== null &&
      `Winners took ${priceDelta(bot.avg_mae_on_winners)} of heat — close to the stop distance means the stops have no room left.`,
  ].filter(Boolean);
  return (
    <span title={hints.length > 0 ? hints.join("\n") : undefined}>
      <span className="text-ok">{priceDelta(bot.avg_mfe)}</span>
      <span className="text-ink-muted"> / </span>
      <span className="text-err">{priceDelta(bot.avg_mae)}</span>
      {bot.mfe_mae_ratio !== null && (
        <span className="ml-1 text-xs text-ink-muted">({bot.mfe_mae_ratio.toFixed(2)}x)</span>
      )}
    </span>
  );
}

/** Broker return codes seen on this bot's fills. A clean fleet shows only
 * 10009; anything else is called out, because a recurring refusal code
 * (10016 invalid stops killed a whole VIX75 fleet once) otherwise only
 * exists in log text nobody reads. */
function RetcodeBadges({ codes }: { codes: BotAnalytics["retcode_histogram"] }) {
  if (codes.length === 0) return <span className="text-ink-muted">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map(({ retcode, count }) => (
        <span
          key={retcode}
          className={`rounded px-1.5 py-0.5 text-2xs font-semibold ${
            retcode === RETCODE_DONE ? "bg-ok/15 text-ok" : "bg-err/15 text-err"
          }`}
          title={
            retcode === RETCODE_DONE
              ? `${count} fill(s) completed cleanly (MT5 10009).`
              : `${count} fill(s) returned MT5 code ${retcode} — not a clean deal.`
          }
        >
          {retcode}
          <span className="ml-1 font-normal opacity-70">x{count}</span>
        </span>
      ))}
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
