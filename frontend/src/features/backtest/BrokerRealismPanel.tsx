"use client";

import { memo } from "react";
import type { BrokerRealism } from "@/shared/api/client";

interface Props {
  realism: BrokerRealism | undefined;
}

/** What the simulated broker enforced during this run, and how many entries it
 * refused (OBSERVABILITY_PLAN.md Phase 4).
 *
 * The rejection counts are the point: before they existed, an M1 scalp whose
 * stops sat inside the symbol's `stops_level` produced a clean equity curve
 * here while every live order was refused with MT5 retcode 10016. A run that
 * simulated nothing says so loudly rather than showing an empty table, because
 * "no rejections shown" and "rejections never checked" mean opposite things.
 */
export const BrokerRealismPanel = memo(function BrokerRealismPanel({ realism }: Props) {
  if (realism === undefined || !realism.enabled) {
    return (
      <section className="rounded-md border border-sell/40 bg-panel">
        <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
          Broker realism
        </header>
        <p className="px-3 py-2 text-sm text-sell">
          Not simulated. These trades were filled at each bar&apos;s closing quote in the exact lot
          size requested, so some may be entries a real broker would refuse — stops closer to price
          than the symbol&apos;s <code>stops_level</code>, or lot sizes off its volume grid. Re-run
          the backtest to get broker-legal numbers.
        </p>
      </section>
    );
  }

  const attempted = realism.accepted_count + realism.rejected_count;
  const acceptance = attempted > 0 ? realism.accepted_count / attempted : 0;
  const allRefused = attempted > 0 && realism.accepted_count === 0;

  return (
    <section className="rounded-md border border-line bg-panel">
      <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
        Broker realism — entries checked against the symbol&apos;s real{" "}
        <code>stops_level</code>, lot grid, spread and slippage.
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-3 py-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-ink-muted">Filled</dt>
          <dd className="text-ok">{realism.accepted_count}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Refused</dt>
          <dd className={realism.rejected_count > 0 ? "text-err" : "text-ink"}>
            {realism.rejected_count}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Acceptance rate</dt>
          <dd className={allRefused ? "text-err" : "text-ink"}>
            {(acceptance * 100).toFixed(1)}%
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Slippage per fill</dt>
          <dd
            className={realism.slippage_source === "fallback" ? "text-sell" : "text-ink"}
            title={
              realism.slippage_source === "live"
                ? `Calibrated from ${realism.slippage_sample_count} real measured live fills on this symbol.`
                : "Not enough live fills yet to calibrate — a documented pessimistic default was used, so this figure is a guess."
            }
          >
            {realism.slippage_mean >= 0 ? "+" : ""}
            {realism.slippage_mean.toFixed(5)} ± {realism.slippage_stddev.toFixed(5)}{" "}
            <span className="text-xs text-ink-muted">({realism.slippage_source})</span>
          </dd>
        </div>
      </dl>

      {allRefused && (
        <p className="border-t border-line px-3 py-2 text-sm text-err">
          Every entry this strategy attempted was refused. Its results above are not achievable —
          the broker would never have placed a single one of these orders.
        </p>
      )}

      {realism.clamped_count > 0 && (
        <p className="border-t border-line px-3 py-2 text-sm text-sell">
          {realism.clamped_count} {realism.clamped_count === 1 ? "entry" : "entries"} had their
          SL/TP widened to the broker minimum instead of being refused. Those positions risked more
          than the risk manager sized them for, so their R multiples are not comparable with a
          normal run&apos;s.
        </p>
      )}

      {realism.spread_widening_factor > 1 && (
        <p className="border-t border-line px-3 py-2 text-xs text-ink-muted">
          Spread widened {realism.spread_widening_factor.toFixed(2)}× over each bar&apos;s recorded
          closing spread, since real entries do not happen at the close.
        </p>
      )}

      {realism.rejections.length > 0 && (
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-muted">
                <th className="px-3 py-2 font-medium">Refused for</th>
                <th className="px-3 py-2 text-right font-medium">Count</th>
                <th className="px-3 py-2 text-right font-medium">MT5 retcode</th>
                <th className="px-3 py-2 font-medium">Example</th>
              </tr>
            </thead>
            <tbody>
              {realism.rejections.map((r) => (
                <tr key={r.reason} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 whitespace-nowrap text-err">{r.reason}</td>
                  <td className="px-3 py-2 text-right">{r.count}</td>
                  <td className="px-3 py-2 text-right text-ink-muted">{r.retcode}</td>
                  <td
                    className="max-w-[420px] truncate px-3 py-2 text-ink-muted"
                    title={r.example}
                  >
                    {r.example}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
});
