"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getBacktestReports, type BacktestReportSummary } from "@/shared/api/client";

/** List of saved backtest reports (written by `python -m src.backtest.cli` /
 * `make backtest`) — table of headline stats, each row linking to its detail
 * page. Read-only: there is no "run a backtest" button here, by design (see
 * the `backtest` API tag description). */
export function BacktestReportList() {
  const [reports, setReports] = useState<BacktestReportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBacktestReports()
      .then(setReports)
      .catch(() => setError("failed to load backtest reports"));
  }, []);

  if (error) return <p className="p-4 text-sm text-err">{error}</p>;
  if (reports === null) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;
  if (reports.length === 0) {
    return (
      <p className="p-4 text-sm text-ink-muted">
        No backtest reports yet — run{" "}
        <code className="rounded bg-panel px-1 py-0.5 text-ink">
          make backtest strategy=&lt;name&gt; symbol=&lt;symbol&gt; period=YYYY-MM:YYYY-MM
        </code>{" "}
        from the repo root.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto p-4">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-muted">
            <Th>Strategy</Th>
            <Th>Symbol</Th>
            <Th>Period</Th>
            <Th align="right">Trades</Th>
            <Th align="right">Win rate</Th>
            <Th align="right">Profit factor</Th>
            <Th align="right">Max DD</Th>
            <Th align="right">Ending balance</Th>
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr
              key={r.id}
              className="border-b border-line last:border-0 hover:bg-panel/60"
            >
              <Td>
                <Link href={`/backtest/${encodeURIComponent(r.id)}`} className="text-accent hover:underline">
                  {r.strategy}
                </Link>
              </Td>
              <Td>{r.symbol}</Td>
              <Td>{r.period}</Td>
              <Td align="right">{r.trade_count}</Td>
              <Td align="right">{(r.win_rate * 100).toFixed(1)}%</Td>
              <Td align="right">{r.profit_factor === null ? "∞" : r.profit_factor.toFixed(2)}</Td>
              <Td align="right">{r.max_drawdown_pct.toFixed(2)}%</Td>
              <Td align="right" tone={r.ending_balance >= r.starting_balance ? "ok" : "err"}>
                {r.ending_balance.toFixed(2)}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return <th className={`py-2 pr-4 font-medium ${align === "right" ? "text-right" : ""}`}>{children}</th>;
}

function Td({
  children,
  align = "left",
  tone = "neutral",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  tone?: "neutral" | "ok" | "err";
}) {
  const toneCls = tone === "ok" ? "text-ok" : tone === "err" ? "text-err" : "";
  return (
    <td className={`py-2 pr-4 ${align === "right" ? "text-right" : ""} ${toneCls}`}>{children}</td>
  );
}
