"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  deleteBacktestReport,
  getBacktestReports,
  type BacktestReportSummary,
} from "@/shared/api/client";
import { RunBacktestPanel } from "./RunBacktestPanel";

const PAGE_SIZE = 10;

/** Full backtest page: a launcher panel at the top, followed by the saved
 *  report list. The panel's `onDone` callback re-fetches the report list
 *  so the new report appears immediately once the backtest finishes. */
export function BacktestReportList() {
  const [reports, setReports] = useState<BacktestReportSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const fetchReports = useCallback((pageToLoad: number) => {
    getBacktestReports(PAGE_SIZE, pageToLoad * PAGE_SIZE)
      .then((res) => {
        setReports(res.items);
        setTotal(res.total);
        setError(null);
      })
      .catch(() => setError("failed to load backtest reports"));
  }, []);

  useEffect(() => {
    fetchReports(page);
  }, [fetchReports, page]);

  const handleJobDone = useCallback(
    (_reportId: string) => {
      setPage(0);
      fetchReports(0);
    },
    [fetchReports],
  );

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function handleDelete(id: string, label: string) {
    if (!window.confirm(`Permanently delete the report for ${label}? This cannot be undone.`)) return;
    setDeletingId(id);
    setDeleteError(null);
    try {
      await deleteBacktestReport(id);
      if (reports?.length === 1 && page > 0) setPage(page - 1);
      else fetchReports(page);
    } catch (e) {
      setDeleteError(e instanceof ApiError ? e.message : "failed to delete report");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div>
      {/* ── Run Backtest Launcher ─────────────────────────────────────────── */}
      <RunBacktestPanel onDone={handleJobDone} />

      {/* ── Saved Report List ─────────────────────────────────────────────── */}
      <div className="report-list-section">
        <div className="report-list-header">
          <div className="report-list-header-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M9 12h6M9 16h6M7 4h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
            </svg>
          </div>
          <h3 className="report-list-title">Saved Reports</h3>
          <button
            className="report-list-refresh"
            onClick={() => fetchReports(page)}
            title="Refresh report list"
            id="refresh-reports-btn"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 4v6h6M23 20v-6h-6" />
              <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
            </svg>
          </button>
        </div>

        {error && <p className="report-list-err">{error}</p>}
        {deleteError && <p className="report-list-err">{deleteError}</p>}
        {!error && reports === null && (
          <p className="report-list-loading">Loading…</p>
        )}
        {!error && reports !== null && reports.length === 0 && (
          <div className="report-list-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M9 12h6M9 16h6M7 4h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
            </svg>
            <p>No reports yet — run a backtest above.</p>
          </div>
        )}
        {!error && reports && reports.length > 0 && (
          <div className="overflow-x-auto">
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
                  <Th align="right">{""}</Th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-line last:border-0 hover:bg-panel/60"
                  >
                    <Td>
                      <Link
                        href={`/backtest/${encodeURIComponent(r.id)}`}
                        className="text-accent hover:underline"
                      >
                        {r.strategy}
                      </Link>
                    </Td>
                    <Td>{r.symbol}</Td>
                    <Td>{r.period}</Td>
                    <Td align="right">{r.trade_count}</Td>
                    <Td align="right">{(r.win_rate * 100).toFixed(1)}%</Td>
                    <Td align="right">
                      {r.profit_factor === null ? "∞" : r.profit_factor.toFixed(2)}
                    </Td>
                    <Td align="right">{r.max_drawdown_pct.toFixed(2)}%</Td>
                    <Td
                      align="right"
                      tone={r.ending_balance >= r.starting_balance ? "ok" : "err"}
                    >
                      {r.ending_balance.toFixed(2)}
                    </Td>
                    <Td align="right">
                      <button
                        type="button"
                        className="report-list-delete-btn"
                        disabled={deletingId !== null}
                        onClick={() => handleDelete(r.id, `${r.strategy} / ${r.symbol} / ${r.period}`)}
                        title="Delete this report"
                      >
                        {deletingId === r.id ? "…" : "Delete"}
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!error && reports && total > 0 && (
          <div className="report-list-pager">
            <span className="report-list-pager-info">
              {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
            </span>
            <div className="report-list-pager-btns">
              <button
                className="report-list-pager-btn"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                Prev
              </button>
              <span className="report-list-pager-info">
                Page {page + 1} of {pageCount}
              </span>
              <button
                className="report-list-pager-btn"
                disabled={page + 1 >= pageCount}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      <style>{`
        .report-list-section {
          margin: 0 16px 24px;
        }
        .report-list-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 12px;
          padding-top: 4px;
        }
        .report-list-header-icon {
          width: 28px; height: 28px;
          background: rgba(99,102,241,.15);
          border-radius: 6px;
          display: flex; align-items: center; justify-content: center;
          color: #818cf8;
        }
        .report-list-header-icon svg { width: 15px; height: 15px; }
        .report-list-title {
          font-size: 14px;
          font-weight: 700;
          color: var(--ink, #f1f5f9);
          flex: 1;
        }
        .report-list-refresh {
          width: 28px; height: 28px;
          display: flex; align-items: center; justify-content: center;
          background: rgba(255,255,255,.05);
          border: 1px solid rgba(255,255,255,.1);
          border-radius: 6px;
          color: var(--ink-muted, #94a3b8);
          cursor: pointer;
          transition: all .15s;
        }
        .report-list-refresh:hover {
          background: rgba(99,102,241,.15);
          color: #818cf8;
          border-color: rgba(99,102,241,.4);
        }
        .report-list-refresh svg { width: 13px; height: 13px; }
        .report-list-err {
          font-size: 13px; color: #f87171; padding: 8px 0;
        }
        .report-list-loading {
          font-size: 13px; color: var(--ink-muted, #94a3b8); padding: 8px 0;
        }
        .report-list-empty {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
          padding: 32px 0;
          color: var(--ink-muted, #94a3b8);
          font-size: 13px;
        }
        .report-list-empty svg {
          width: 32px; height: 32px;
          opacity: .4;
        }
        .report-list-pager {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-top: 12px;
          font-size: 12px;
          color: var(--ink-muted, #94a3b8);
        }
        .report-list-pager-btns {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .report-list-pager-btn {
          padding: 4px 10px;
          background: rgba(255,255,255,.05);
          border: 1px solid rgba(255,255,255,.1);
          border-radius: 6px;
          color: var(--ink, #f1f5f9);
          font-size: 12px;
          cursor: pointer;
          transition: all .15s;
        }
        .report-list-pager-btn:hover:not(:disabled) {
          background: rgba(99,102,241,.15);
          border-color: rgba(99,102,241,.4);
        }
        .report-list-pager-btn:disabled {
          opacity: .4;
          cursor: not-allowed;
        }
        .report-list-delete-btn {
          padding: 3px 8px;
          background: rgba(255,255,255,.05);
          border: 1px solid rgba(255,255,255,.1);
          border-radius: 6px;
          color: var(--ink-muted, #94a3b8);
          font-size: 11px;
          cursor: pointer;
          transition: all .15s;
        }
        .report-list-delete-btn:hover:not(:disabled) {
          background: rgba(248,113,113,.15);
          color: #f87171;
          border-color: rgba(248,113,113,.4);
        }
        .report-list-delete-btn:disabled {
          opacity: .4;
          cursor: not-allowed;
        }
      `}</style>
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
    <td className={`py-2 pr-4 ${align === "right" ? "text-right" : ""} ${toneCls}`}>
      {children}
    </td>
  );
}
