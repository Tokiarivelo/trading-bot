"use client";

import { useEffect, useRef, useState } from "react";
import {
  type BacktestBot,
  type BacktestJobStatus,
  getBacktestBots,
  getBacktestJobStatus,
  startBacktest,
} from "@/shared/api/client";

interface RunBacktestPanelProps {
  /** Called when a backtest completes so the report list can refresh. */
  onDone: (reportId: string) => void;
}

// ── Period helpers ────────────────────────────────────────────────────────────

function defaultPeriod(): { from: string; to: string } {
  const now = new Date();
  const to = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const from = `${now.getFullYear() - 1}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return { from, to };
}

/** "YYYY-MM" strings sort correctly as plain strings, so this is enough to
 * guarantee `from <= to` regardless of which field the user edited last —
 * needed because the two `<input type="month">` fields below no longer
 * cross-constrain each other live via `min`/`max` (that caused an edit to
 * one field to silently get dropped by the browser when the other field's
 * bound changed mid-interaction — the resulting period sent to the backend
 * didn't match what was shown on screen). */
function normalizePeriod(from: string, to: string): { from: string; to: string } {
  return from <= to ? { from, to } : { from: to, to: from };
}

function periodToString(from: string, to: string): string {
  const normalized = normalizePeriod(from, to);
  return `${normalized.from}:${normalized.to}`;
}

const DEFAULT_STARTING_BALANCE = 10_000;

// ── Component ─────────────────────────────────────────────────────────────────

export function RunBacktestPanel({ onDone }: RunBacktestPanelProps) {
  const [bots, setBots] = useState<BacktestBot[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [selectedBotId, setSelectedBotId] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [period, setPeriod] = useState(defaultPeriod);
  const [startingBalance, setStartingBalance] = useState(String(DEFAULT_STARTING_BALANCE));
  const [overrideFallback, setOverrideFallback] = useState(false);
  const [fallbackEnabled, setFallbackEnabled] = useState(true);
  const [fallbackCeiling, setFallbackCeiling] = useState("");
  const [overrideMinRr, setOverrideMinRr] = useState(false);
  const [minRr, setMinRr] = useState("");

  const [job, setJob] = useState<BacktestJobStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load bots on mount
  useEffect(() => {
    getBacktestBots()
      .then(setBots)
      .catch(() => setLoadErr("Failed to load bots"));
  }, []);

  // Poll job status while running
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") {
      if (pollRef.current) clearInterval(pollRef.current);
      if (job?.status === "done" && job.report_id) {
        onDone(job.report_id);
      }
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const updated = await getBacktestJobStatus(job.job_id);
        setJob(updated);
      } catch {
        // ignore transient poll errors
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job, onDone]);

  const selectedBot = bots?.find((b) => b.id === selectedBotId) ?? null;

  function handleSelectBot(botId: string) {
    if (selectedBotId === botId) {
      setSelectedBotId(null);
      setSelectedSymbol(null);
      return;
    }
    const bot = bots?.find((b) => b.id === botId);
    setSelectedBotId(botId);
    setSelectedSymbol(bot?.symbols[0] ?? null);
  }

  const parsedBalance = Number(startingBalance);
  const isBalanceValid = startingBalance.trim() !== "" && Number.isFinite(parsedBalance) && parsedBalance > 0;

  const parsedCeiling = fallbackCeiling.trim() === "" ? null : Number(fallbackCeiling);
  const isCeilingValid =
    parsedCeiling === null || (Number.isFinite(parsedCeiling) && parsedCeiling > 0 && parsedCeiling <= 100);

  const parsedMinRr = minRr.trim() === "" ? null : Number(minRr);
  const isMinRrValid =
    !overrideMinRr || (parsedMinRr !== null && Number.isFinite(parsedMinRr) && parsedMinRr > 0);

  async function handleRun() {
    if (!selectedBotId || !selectedSymbol || !isBalanceValid || !isCeilingValid || !isMinRrValid) return;
    setRunErr(null);
    setSubmitting(true);
    setJob(null);
    try {
      const newJob = await startBacktest(
        selectedBotId,
        selectedSymbol,
        periodToString(period.from, period.to),
        parsedBalance,
        overrideFallback ? fallbackEnabled : undefined,
        overrideFallback && parsedCeiling !== null ? parsedCeiling : undefined,
        overrideMinRr && parsedMinRr !== null ? parsedMinRr : undefined,
      );
      setJob(newJob);
    } catch (e: unknown) {
      setRunErr(e instanceof Error ? e.message : "Failed to start backtest");
    } finally {
      setSubmitting(false);
    }
  }

  const isRunning = job?.status === "pending" || job?.status === "running";
  const isDone = job?.status === "done";
  const isError = job?.status === "error";

  return (
    <div className="run-backtest-panel">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="run-panel-header">
        <div className="run-panel-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="5,3 19,12 5,21" />
          </svg>
        </div>
        <div>
          <h2 className="run-panel-title">Run Backtest</h2>
          <p className="run-panel-sub">Select a bot, symbol, and period to start</p>
        </div>
      </div>

      <div className="run-panel-body">
        {/* ── Bot list ───────────────────────────────────────────────────── */}
        <section className="run-panel-section">
          <label className="run-panel-label">
            <span className="run-panel-label-dot" style={{ background: "var(--accent)" }} />
            Bots
          </label>
          {loadErr ? (
            <p className="run-panel-err">{loadErr}</p>
          ) : !bots ? (
            <div className="run-panel-loading">
              <span className="run-panel-spinner" />
              Loading bots…
            </div>
          ) : bots.length === 0 ? (
            <p className="run-panel-empty">No bots configured — add a skill YAML under <code>backend/src/skills/normal/</code>.</p>
          ) : (
            <div className="bot-grid">
              {bots.map((bot) => (
                <button
                  key={bot.id}
                  className={`bot-card ${selectedBotId === bot.id ? "bot-card--active" : ""}`}
                  onClick={() => handleSelectBot(bot.id)}
                  id={`bot-card-${bot.id}`}
                >
                  <div className="bot-card-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <rect x="3" y="3" width="18" height="18" rx="3" />
                      <path d="M8 12h8M12 8v8" />
                    </svg>
                  </div>
                  <span className="bot-card-name">{bot.name}</span>
                  <span className="bot-card-count">{bot.symbols.length} symbol{bot.symbols.length !== 1 ? "s" : ""}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* ── Symbol list ────────────────────────────────────────────────── */}
        <section className={`run-panel-section ${!selectedBot ? "run-panel-section--dim" : ""}`}>
          <label className="run-panel-label">
            <span className="run-panel-label-dot" style={{ background: "#a78bfa" }} />
            Symbol
          </label>
          {selectedBot ? (
            <div className="symbol-grid">
              {selectedBot.symbols.map((sym) => (
                <button
                  key={sym}
                  className={`symbol-chip ${selectedSymbol === sym ? "symbol-chip--active" : ""}`}
                  onClick={() => setSelectedSymbol(sym)}
                  id={`symbol-chip-${sym}`}
                >
                  {sym}
                </button>
              ))}
            </div>
          ) : (
            <p className="run-panel-empty run-panel-empty--sm">← Pick a bot first</p>
          )}
        </section>

        {/* ── Period ─────────────────────────────────────────────────────── */}
        <section className={`run-panel-section ${!selectedBot ? "run-panel-section--dim" : ""}`}>
          <label className="run-panel-label">
            <span className="run-panel-label-dot" style={{ background: "#34d399" }} />
            Period
          </label>
          <div className="period-row">
            <div className="period-field">
              <span className="period-field-label">From</span>
              <input
                type="month"
                className="period-input"
                value={period.from}
                onChange={(e) => setPeriod((p) => ({ ...p, from: e.target.value }))}
                id="backtest-period-from"
              />
            </div>
            <div className="period-sep">→</div>
            <div className="period-field">
              <span className="period-field-label">To</span>
              <input
                type="month"
                className="period-input"
                value={period.to}
                onChange={(e) => setPeriod((p) => ({ ...p, to: e.target.value }))}
                id="backtest-period-to"
              />
            </div>
          </div>
          <p className="period-hint">
            Format: <code>{periodToString(period.from, period.to)}</code>
          </p>
        </section>

        {/* ── Starting balance ──────────────────────────────────────────── */}
        <section className={`run-panel-section ${!selectedBot ? "run-panel-section--dim" : ""}`}>
          <label className="run-panel-label">
            <span className="run-panel-label-dot" style={{ background: "#fbbf24" }} />
            Starting balance
          </label>
          <div className="balance-field">
            <span className="balance-field-prefix">$</span>
            <input
              type="number"
              min="0"
              step="100"
              className="balance-input"
              value={startingBalance}
              onChange={(e) => setStartingBalance(e.target.value)}
              id="backtest-starting-balance"
            />
          </div>
          {!isBalanceValid && (
            <p className="period-hint" style={{ color: "#f87171" }}>
              Enter a balance greater than 0.
            </p>
          )}
        </section>

        {/* ── Min-lot fallback override ─────────────────────────────────── */}
        <section className={`run-panel-section ${!selectedBot ? "run-panel-section--dim" : ""}`}>
          <label className="run-panel-label">
            <span className="run-panel-label-dot" style={{ background: "#f87171" }} />
            Small balance
          </label>
          <label className="fallback-toggle">
            <input
              type="checkbox"
              checked={overrideFallback}
              onChange={(e) => setOverrideFallback(e.target.checked)}
              id="backtest-override-fallback"
            />
            Override min-lot fallback for this run
          </label>
          {overrideFallback && (
            <div className="fallback-row">
              <label className="fallback-toggle">
                <input
                  type="checkbox"
                  checked={fallbackEnabled}
                  onChange={(e) => setFallbackEnabled(e.target.checked)}
                  id="backtest-fallback-enabled"
                />
                Trade minimum lot when risk % alone is too small
              </label>
              <div className="balance-field" style={{ maxWidth: 110 }}>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.5"
                  disabled={!fallbackEnabled}
                  className="balance-input"
                  value={fallbackCeiling}
                  onChange={(e) => setFallbackCeiling(e.target.value)}
                  placeholder="ceiling %"
                  id="backtest-fallback-ceiling"
                />
                <span className="balance-field-prefix">%</span>
              </div>
            </div>
          )}
          <p className="period-hint">
            Tests a different min-lot fallback than <code>configs/risk.yaml</code> (or the live
            override) without touching either — one-off, this run only. Ceiling is the max
            effective risk (%) the minimum lot is allowed to carry.
          </p>
          {overrideFallback && !isCeilingValid && (
            <p className="period-hint" style={{ color: "#f87171" }}>
              Ceiling must be between 0 and 100.
            </p>
          )}

          <label className="fallback-toggle" style={{ marginTop: 10 }}>
            <input
              type="checkbox"
              checked={overrideMinRr}
              onChange={(e) => setOverrideMinRr(e.target.checked)}
              id="backtest-override-min-rr"
            />
            Override minimum RR for this run
          </label>
          {overrideMinRr && (
            <div className="fallback-row">
              <div className="balance-field" style={{ maxWidth: 110 }}>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  className="balance-input"
                  value={minRr}
                  onChange={(e) => setMinRr(e.target.value)}
                  placeholder="min RR"
                  id="backtest-min-rr"
                />
              </div>
            </div>
          )}
          <p className="period-hint">
            Overrides <code>configs/symbols/&lt;symbol&gt;.yaml</code>&apos;s min_rr — a tighter-
            stop strategy (e.g. a scalping variant) can fail the spread-adjusted RR floor a
            swing-trading min_rr was tuned for.
          </p>
          {overrideMinRr && !isMinRrValid && (
            <p className="period-hint" style={{ color: "#f87171" }}>
              Enter a minimum RR greater than 0.
            </p>
          )}
        </section>

        {/* ── Run button ─────────────────────────────────────────────────── */}
        <div className="run-panel-actions">
          <button
            className={`run-btn ${isRunning ? "run-btn--busy" : ""}`}
            onClick={handleRun}
            disabled={
              !selectedBotId ||
              !selectedSymbol ||
              !isBalanceValid ||
              !isCeilingValid ||
              !isMinRrValid ||
              isRunning ||
              submitting
            }
            id="run-backtest-btn"
          >
            {submitting || isRunning ? (
              <>
                <span className="run-btn-spinner" />
                {submitting ? "Starting…" : "Running backtest…"}
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" fill="currentColor" className="run-btn-icon">
                  <polygon points="5,3 19,12 5,21" />
                </svg>
                Run Backtest
              </>
            )}
          </button>
        </div>

        {/* ── Status feedback ────────────────────────────────────────────── */}
        {runErr && (
          <div className="run-feedback run-feedback--err">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="run-feedback-icon">
              <circle cx="12" cy="12" r="10" /><path d="M15 9l-6 6M9 9l6 6" />
            </svg>
            {runErr}
          </div>
        )}
        {job && isError && (
          <div className="run-feedback run-feedback--err">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="run-feedback-icon">
              <circle cx="12" cy="12" r="10" /><path d="M15 9l-6 6M9 9l6 6" />
            </svg>
            {job.error ?? "Backtest failed"}
          </div>
        )}
        {job && isDone && (
          <div className="run-feedback run-feedback--ok">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="run-feedback-icon">
              <circle cx="12" cy="12" r="10" /><path d="M8 12l3 3 5-5" />
            </svg>
            Backtest complete — report added below.
          </div>
        )}
        {job && isRunning && (
          <div className="run-feedback run-feedback--info">
            <span className="run-panel-spinner run-panel-spinner--sm" />
            Backtest running — this may take a minute. Results will appear automatically.
          </div>
        )}
      </div>

      <style>{`
        .run-backtest-panel {
          background: linear-gradient(135deg, rgba(139,92,246,.08) 0%, rgba(59,130,246,.06) 100%);
          border: 1px solid rgba(139,92,246,.25);
          border-radius: 16px;
          margin: 16px;
          overflow: hidden;
        }
        .run-panel-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 16px 20px;
          background: linear-gradient(90deg, rgba(139,92,246,.18) 0%, transparent 100%);
          border-bottom: 1px solid rgba(139,92,246,.15);
        }
        .run-panel-icon {
          width: 40px;
          height: 40px;
          background: linear-gradient(135deg, #7c3aed, #4f46e5);
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          flex-shrink: 0;
        }
        .run-panel-icon svg { width: 18px; height: 18px; }
        .run-panel-title {
          font-size: 15px;
          font-weight: 700;
          color: var(--ink, #f1f5f9);
          margin: 0;
        }
        .run-panel-sub {
          font-size: 12px;
          color: var(--ink-muted, #94a3b8);
          margin: 0;
        }
        .run-panel-body {
          padding: 16px 20px 20px;
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .run-panel-section {
          display: flex;
          flex-direction: column;
          gap: 10px;
          transition: opacity .2s;
        }
        .run-panel-section--dim { opacity: .45; pointer-events: none; }
        .run-panel-label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: .06em;
          text-transform: uppercase;
          color: var(--ink-muted, #94a3b8);
        }
        .run-panel-label-dot {
          width: 6px; height: 6px; border-radius: 50%;
        }
        .run-panel-loading {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: var(--ink-muted, #94a3b8);
        }
        .run-panel-empty {
          font-size: 13px;
          color: var(--ink-muted, #94a3b8);
        }
        .run-panel-empty--sm { font-size: 12px; }
        .run-panel-err { font-size: 13px; color: #f87171; }

        /* Bot grid */
        .bot-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .bot-card {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
          padding: 10px 14px;
          background: rgba(255,255,255,.04);
          border: 1px solid rgba(255,255,255,.1);
          border-radius: 10px;
          cursor: pointer;
          transition: all .18s;
          min-width: 140px;
          text-align: left;
        }
        .bot-card:hover {
          background: rgba(139,92,246,.12);
          border-color: rgba(139,92,246,.4);
          transform: translateY(-1px);
        }
        .bot-card--active {
          background: linear-gradient(135deg, rgba(139,92,246,.22), rgba(79,70,229,.18));
          border-color: rgba(139,92,246,.65);
          box-shadow: 0 0 0 1px rgba(139,92,246,.3), 0 4px 12px rgba(139,92,246,.15);
        }
        .bot-card-icon {
          width: 28px; height: 28px;
          background: rgba(139,92,246,.2);
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #a78bfa;
        }
        .bot-card-icon svg { width: 16px; height: 16px; }
        .bot-card-name {
          font-size: 13px;
          font-weight: 600;
          color: var(--ink, #f1f5f9);
          word-break: break-all;
        }
        .bot-card--active .bot-card-name { color: #c4b5fd; }
        .bot-card-count {
          font-size: 11px;
          color: var(--ink-muted, #94a3b8);
        }

        /* Symbol chips */
        .symbol-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .symbol-chip {
          padding: 6px 14px;
          font-size: 13px;
          font-weight: 600;
          border-radius: 20px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.05);
          color: var(--ink, #f1f5f9);
          cursor: pointer;
          transition: all .15s;
        }
        .symbol-chip:hover {
          border-color: rgba(167,139,250,.5);
          background: rgba(167,139,250,.1);
        }
        .symbol-chip--active {
          background: linear-gradient(135deg, #7c3aed, #4f46e5);
          border-color: #7c3aed;
          color: #fff;
          box-shadow: 0 2px 8px rgba(124,58,237,.35);
        }

        /* Period */
        .period-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .period-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .period-field-label {
          font-size: 11px;
          color: var(--ink-muted, #94a3b8);
        }
        .period-input {
          padding: 7px 12px;
          background: rgba(255,255,255,.06);
          border: 1px solid rgba(255,255,255,.12);
          border-radius: 8px;
          color: var(--ink, #f1f5f9);
          font-size: 13px;
          color-scheme: dark;
          transition: border-color .15s;
        }
        .period-input:focus {
          outline: none;
          border-color: rgba(139,92,246,.6);
        }
        .period-sep {
          font-size: 16px;
          color: var(--ink-muted, #94a3b8);
          margin-top: 18px;
        }
        .period-hint {
          font-size: 11px;
          color: var(--ink-muted, #94a3b8);
          margin: 0;
        }
        .period-hint code {
          background: rgba(255,255,255,.08);
          padding: 1px 4px;
          border-radius: 3px;
          font-family: monospace;
        }

        /* Starting balance */
        .balance-field {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 7px 12px;
          background: rgba(255,255,255,.06);
          border: 1px solid rgba(255,255,255,.12);
          border-radius: 8px;
          max-width: 180px;
          transition: border-color .15s;
        }
        .balance-field:focus-within {
          border-color: rgba(251,191,36,.6);
        }
        .balance-field-prefix {
          font-size: 13px;
          color: var(--ink-muted, #94a3b8);
        }
        .balance-input {
          flex: 1;
          min-width: 0;
          background: transparent;
          border: none;
          outline: none;
          color: var(--ink, #f1f5f9);
          font-size: 13px;
          color-scheme: dark;
        }

        /* Min-lot fallback override */
        .fallback-toggle {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          color: var(--ink, #f1f5f9);
          cursor: pointer;
        }
        .fallback-row {
          display: flex;
          align-items: center;
          gap: 14px;
          margin-top: 4px;
        }

        /* Run button */
        .run-panel-actions { display: flex; }
        .run-btn {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 24px;
          background: linear-gradient(135deg, #7c3aed, #4f46e5);
          color: #fff;
          font-size: 14px;
          font-weight: 700;
          border-radius: 10px;
          border: none;
          cursor: pointer;
          transition: all .18s;
          box-shadow: 0 4px 12px rgba(124,58,237,.35);
        }
        .run-btn:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 6px 18px rgba(124,58,237,.45);
        }
        .run-btn:disabled {
          opacity: .5;
          cursor: not-allowed;
          transform: none;
          box-shadow: none;
        }
        .run-btn--busy {
          background: rgba(124,58,237,.5);
        }
        .run-btn-icon { width: 16px; height: 16px; }

        /* Spinners */
        .run-panel-spinner {
          display: inline-block;
          width: 14px; height: 14px;
          border: 2px solid rgba(255,255,255,.3);
          border-top-color: #fff;
          border-radius: 50%;
          animation: spin .7s linear infinite;
        }
        .run-panel-spinner--sm {
          width: 12px; height: 12px;
          border-top-color: #60a5fa;
          border-color: rgba(96,165,250,.2);
        }
        .run-btn-spinner {
          display: inline-block;
          width: 14px; height: 14px;
          border: 2px solid rgba(255,255,255,.3);
          border-top-color: #fff;
          border-radius: 50%;
          animation: spin .7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Feedback banners */
        .run-feedback {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 10px 14px;
          border-radius: 8px;
          font-size: 13px;
          line-height: 1.5;
        }
        .run-feedback-icon { width: 16px; height: 16px; flex-shrink: 0; margin-top: 1px; }
        .run-feedback--ok {
          background: rgba(52,211,153,.1);
          border: 1px solid rgba(52,211,153,.3);
          color: #6ee7b7;
        }
        .run-feedback--err {
          background: rgba(248,113,113,.1);
          border: 1px solid rgba(248,113,113,.3);
          color: #fca5a5;
        }
        .run-feedback--info {
          background: rgba(96,165,250,.1);
          border: 1px solid rgba(96,165,250,.25);
          color: #93c5fd;
        }
      `}</style>
    </div>
  );
}
