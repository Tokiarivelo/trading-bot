"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  getRefinementProposal,
  rejectRefinementProposal,
  type BacktestReportSummary,
  type RefinementProposalDetail as ProposalDetail,
} from "@/shared/api/client";
import { StatusBadge } from "@/features/strategies/StatusBadge";
import { StatTile } from "@/features/backtest/StatTile";

/** Full refinement proposal detail: rationale, a hand-rolled diff view (no
 * npm diff library — this is the only screen that needs one), and
 * before/after backtest metrics. Activating (or rejecting) always happens
 * via the strategy version it produced — see the link below — so there is
 * exactly one activation code path in the whole app. */
export function RefinementProposalDetail({ proposalId }: { proposalId: string }) {
  const [proposal, setProposal] = useState<ProposalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function load() {
    getRefinementProposal(proposalId)
      .then(setProposal)
      .catch(() => setError("proposal not found"));
  }

  useEffect(load, [proposalId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function onReject() {
    setBusy(true);
    setError(null);
    try {
      await rejectRefinementProposal(proposalId);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "reject failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && proposal === null) return <p className="p-4 text-sm text-err">{error}</p>;
  if (proposal === null) return <p className="p-4 text-sm text-ink-muted">Loading…</p>;

  const canReject = proposal.status === "pending" || proposal.status === "backtested";

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <Link
          href={`/ai-reports/${proposal.report_id}`}
          className="text-xs text-ink-muted hover:text-accent"
        >
          ← Review
        </Link>
        <div className="mt-1 flex items-center gap-2">
          <h2 className="text-lg font-semibold">{proposal.strategy_name} · refinement</h2>
          <StatusBadge status={proposal.status} />
        </div>
        <p className="text-sm text-ink-muted">
          {proposal.applied_mode
            ? `Decided by ${proposal.applied_mode} policy`
            : "Awaiting a decision"}
          {proposal.improvement_pct !== null &&
            ` · ${proposal.improvement_pct >= 0 ? "+" : ""}${proposal.improvement_pct.toFixed(1)}% avg R vs baseline`}
        </p>
      </div>

      <section className="rounded-md border border-line bg-panel p-3 text-sm">
        <header className="mb-2 text-ink-muted">Rationale</header>
        <p className="whitespace-pre-wrap">{proposal.rationale || "—"}</p>
      </section>

      {proposal.sandbox_errors.length > 0 && (
        <section className="rounded-md border border-err/50 bg-panel p-3 text-sm">
          <header className="mb-2 text-err">Sandbox validation failed</header>
          <ul className="list-inside list-disc text-err">
            {proposal.sandbox_errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {proposal.new_version_id && (
          <Link
            href={`/strategies/versions/${proposal.new_version_id}`}
            className="rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg"
          >
            View strategy version →
          </Link>
        )}
        {canReject && (
          <button
            className="cursor-pointer rounded border border-err px-3 py-1 text-err hover:bg-err hover:text-bg disabled:cursor-not-allowed disabled:opacity-50"
            disabled={busy}
            onClick={onReject}
            type="button"
          >
            {busy ? "Rejecting…" : "Reject"}
          </button>
        )}
        {error && <span className="text-err">{error}</span>}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <BacktestSummary label="Baseline" summary={proposal.baseline_backtest} />
        <BacktestSummary label="Candidate" summary={proposal.candidate_backtest} />
      </div>

      <section className="overflow-x-auto rounded-md border border-line bg-panel">
        <header className="border-b border-line px-3 py-2 text-sm text-ink-muted">
          Diff vs base version
        </header>
        <DiffView lines={proposal.diff} />
      </section>
    </div>
  );
}

function BacktestSummary({
  label,
  summary,
}: {
  label: string;
  summary: BacktestReportSummary | null;
}) {
  if (summary === null) {
    return (
      <div className="col-span-2 rounded-md border border-line bg-panel p-3 text-sm text-ink-muted">
        {label}: no backtest available (missing candle history)
      </div>
    );
  }
  return (
    <>
      <StatTile label={`${label} win rate`} value={`${(summary.win_rate * 100).toFixed(1)}%`} />
      <StatTile
        label={`${label} avg R`}
        value={summary.avg_r.toFixed(2)}
        tone={summary.avg_r >= 0 ? "ok" : "err"}
      />
    </>
  );
}

function DiffView({ lines }: { lines: string[] }) {
  if (lines.length === 0) {
    return <p className="p-3 text-sm text-ink-muted">No differences.</p>;
  }
  return (
    <pre className="max-h-[32rem] overflow-auto p-3 text-xs">
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++")
              ? "bg-ok/10 text-ok"
              : line.startsWith("-") && !line.startsWith("---")
                ? "bg-err/10 text-err"
                : line.startsWith("@@")
                  ? "text-accent"
                  : "text-ink-muted"
          }
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}
