"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getBacktestReport, type BacktestReportDetail as ReportDetail } from "@/shared/api/client";
import { EquityChart } from "./EquityChart";
import { StatTile } from "./StatTile";

export function BacktestReportDetail({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBacktestReport(reportId)
      .then(setReport)
      .catch(() => setError("report not found"));
  }, [reportId]);

  if (error) return <p className="p-4 text-sm text-err">{error}</p>;
  if (report === null) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  const netProfit = report.ending_balance - report.starting_balance;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <Link href="/backtest" className="text-xs text-ink-muted hover:text-accent">
          ← All reports
        </Link>
        <h2 className="mt-1 text-lg font-semibold">
          {report.strategy} on {report.symbol}
        </h2>
        <p className="text-sm text-ink-muted">{report.period}</p>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
        <StatTile label="Trades" value={String(report.trade_count)} />
        <StatTile label="Win rate" value={`${(report.win_rate * 100).toFixed(1)}%`} />
        <StatTile
          label="Profit factor"
          value={report.profit_factor === null ? "∞" : report.profit_factor.toFixed(2)}
        />
        <StatTile label="Max drawdown" value={`${report.max_drawdown_pct.toFixed(2)}%`} tone="err" />
        <StatTile label="Avg R" value={report.avg_r.toFixed(2)} tone={report.avg_r >= 0 ? "ok" : "err"} />
        <StatTile label="Worst losing streak" value={String(report.worst_losing_streak)} />
        <StatTile
          label="Net P/L"
          value={`${netProfit >= 0 ? "+" : ""}${netProfit.toFixed(2)}`}
          tone={netProfit >= 0 ? "ok" : "err"}
        />
      </div>

      <section className="rounded-md border border-line bg-panel">
        <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
          Equity curve — {report.starting_balance.toFixed(2)} → {report.ending_balance.toFixed(2)}
        </header>
        <EquityChart points={report.equity_curve} />
      </section>

      <section className="overflow-x-auto rounded-md border border-line bg-panel">
        <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">Trades</header>
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-muted">
              <th className="px-3 py-2 font-medium">Side</th>
              <th className="px-3 py-2 text-right font-medium">Volume</th>
              <th className="px-3 py-2 font-medium">Open</th>
              <th className="px-3 py-2 text-right font-medium">Open price</th>
              <th className="px-3 py-2 font-medium">Close</th>
              <th className="px-3 py-2 text-right font-medium">Close price</th>
              <th className="px-3 py-2 text-right font-medium">Profit</th>
              <th className="px-3 py-2 text-right font-medium">R</th>
            </tr>
          </thead>
          <tbody>
            {report.trades.map((t, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                <td className={`px-3 py-2 ${t.side === "buy" ? "text-ok" : "text-err"}`}>
                  {t.side.toUpperCase()}
                </td>
                <td className="px-3 py-2 text-right">{t.volume}</td>
                <td className="px-3 py-2 text-ink-muted">{formatTime(t.open_time)}</td>
                <td className="px-3 py-2 text-right">{t.open_price}</td>
                <td className="px-3 py-2 text-ink-muted">{formatTime(t.close_time)}</td>
                <td className="px-3 py-2 text-right">{t.close_price}</td>
                <td className={`px-3 py-2 text-right ${t.profit >= 0 ? "text-ok" : "text-err"}`}>
                  {t.profit >= 0 ? "+" : ""}
                  {t.profit.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right">
                  {t.r_multiple === null ? "—" : t.r_multiple.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
