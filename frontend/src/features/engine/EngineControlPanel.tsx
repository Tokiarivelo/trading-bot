"use client";

import { useEffect, useState } from "react";
import { useActiveAccount } from "@/shared/api/account-context";
import {
  type EngineStatus,
  getEngineStatus,
  killSwitch,
  resumeEngine,
} from "@/shared/api/client";

const POLL_MS = 5000;

export function EngineControlPanel() {
  const accountId = useActiveAccount();
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!accountId) return;
    let cancelled = false;
    const poll = () =>
      getEngineStatus(accountId).then((s) => !cancelled && setStatus(s)).catch(() => {});
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [accountId]);

  async function handleKill() {
    if (!accountId) return;
    if (!window.confirm("Close all open positions and pause the engine?")) return;
    setBusy(true);
    try {
      setStatus(await killSwitch(accountId));
    } finally {
      setBusy(false);
    }
  }

  async function handleResume() {
    if (!accountId) return;
    setBusy(true);
    try {
      setStatus(await resumeEngine(accountId));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return <span className="text-sm text-ink-muted">Bot control: …</span>;

  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-bold ${
            status.paused
              ? "bg-err text-white"
              : status.enabled
                ? "bg-ok text-white"
                : "bg-line text-ink-muted"
          }`}
        >
          {status.paused ? "PAUSED" : status.enabled ? "RUNNING" : "DISABLED"}
        </span>
        {status.paused && status.pause_reason && (
          <span className="text-ink-muted">{status.pause_reason}</span>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-ink-muted">
        <dt>Consecutive losses</dt>
        <dd className="text-right text-ink">{status.consecutive_losses}</dd>
        <dt>Trades today</dt>
        <dd className="text-right text-ink">{status.trades_today}</dd>
        <dt>Daily P/L</dt>
        <dd className={`text-right ${status.daily_pnl < 0 ? "text-err" : "text-ink"}`}>
          {status.daily_pnl.toFixed(2)}
        </dd>
      </dl>
      <div className="flex gap-2">
        {status.paused ? (
          <button
            onClick={handleResume}
            disabled={busy}
            className="flex-1 cursor-pointer rounded bg-ok px-2 py-1 font-bold text-white disabled:opacity-50"
          >
            Resume
          </button>
        ) : (
          <button
            onClick={handleKill}
            disabled={busy}
            className="flex-1 cursor-pointer rounded bg-err px-2 py-1 font-bold text-white disabled:opacity-50"
          >
            Kill Switch
          </button>
        )}
      </div>
    </div>
  );
}
