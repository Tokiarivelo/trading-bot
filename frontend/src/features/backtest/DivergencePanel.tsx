"use client";

import { useEffect, useState } from "react";
import { getBacktestDivergence, type DivergenceReport } from "@/shared/api/client";

const VERDICT_META: Record<string, { label: string; className: string }> = {
  aligned: { label: "Aligned", className: "text-ok" },
  simulator_optimistic: { label: "Simulator optimistic", className: "text-err" },
  edge_decayed: { label: "Edge decayed", className: "text-err" },
  both: { label: "Both diverge", className: "text-err" },
  insufficient_data: { label: "Not enough data", className: "text-ink-muted" },
};

/** Percent-style metrics read as percentages; the rest are raw values. */
const PERCENT_METRICS = new Set(["fill_rate", "win_rate"]);

function formatValue(name: string, value: number | null): string {
  if (value === null) return "—";
  if (PERCENT_METRICS.has(name)) return `${(value * 100).toFixed(1)}%`;
  return Math.abs(value) < 1 ? value.toFixed(5) : value.toFixed(2);
}

/** Live-vs-backtest divergence for one report (OBSERVABILITY_PLAN.md Phase 4).
 *
 * A profitable backtest and a losing account have two very different causes:
 * the simulator filling better than the broker does, or the edge having
 * decayed. Which metrics diverge — execution or outcome — is what tells them
 * apart, so they are grouped and labelled rather than averaged into a score.
 */
export function DivergencePanel({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<DivergenceReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    setError(null);
    getBacktestDivergence(reportId)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch(() => {
        if (!cancelled) setError("could not compute divergence for this report");
      });
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const verdict = report === null ? null : (VERDICT_META[report.verdict] ?? VERDICT_META.aligned);

  return (
    <section className="rounded-md border border-line bg-panel">
      <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
        Live vs backtest — is the simulator lying about fills, or has the edge decayed?
      </header>

      {error !== null && <p className="px-3 py-2 text-sm text-err">{error}</p>}
      {error === null && report === null && (
        <p className="px-3 py-2 text-sm text-ink-muted">Loading…</p>
      )}

      {report !== null && verdict !== null && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-3 py-3">
            <span className={`text-sm font-semibold ${verdict.className}`}>{verdict.label}</span>
            <span className="text-xs text-ink-muted">
              {report.live_trade_count} live · {report.backtest_trade_count} backtested trades
            </span>
          </div>
          <p className="px-3 pb-3 text-sm text-ink-muted">{report.summary}</p>

          <div className="overflow-x-auto border-t border-line">
            <table className="w-full min-w-[680px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-muted">
                  <th className="px-3 py-2 font-medium">Metric</th>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 text-right font-medium">Live</th>
                  <th className="px-3 py-2 text-right font-medium">Backtest</th>
                  <th className="px-3 py-2 text-right font-medium">Gap</th>
                </tr>
              </thead>
              <tbody>
                {report.metrics.map((m) => (
                  <tr key={m.name} className="border-b border-line last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap" title={m.note}>
                      {m.name}
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-muted">{m.kind}</td>
                    <td className="px-3 py-2 text-right">{formatValue(m.name, m.live_value)}</td>
                    <td className="px-3 py-2 text-right">
                      {formatValue(m.name, m.backtest_value)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right ${m.significant ? "text-err" : "text-ink-muted"}`}
                      title={m.significant ? m.note : "within tolerance"}
                    >
                      {m.relative_delta === null
                        ? "—"
                        : `${m.relative_delta >= 0 ? "+" : ""}${(m.relative_delta * 100).toFixed(0)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
