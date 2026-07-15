"use client";

/**
 * ActivityLogDock — TradingView-style panel showing the bot's persisted
 * activity log (signals, HTF vetoes, risk gate blocks, spread vetoes,
 * fills, circuit breakers) for the chart's current symbol, so "why did it
 * just do that" is answerable without leaving the chart.
 *
 * Rendered inside ChartPanel below the chart header when the user clicks
 * the "Activity log" toggle button, same slot/style as IndicatorsDock.
 * Polls every 5s while open — there's no WS feed for this yet, and 5s is
 * plenty for a human reading log lines (see IMPLEMENTATION_PLAN's Socket.IO
 * note: only live candle streaming needs that path).
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, getActivityLog, type LogEntry } from "@/shared/api/client";

const POLL_INTERVAL_MS = 5000;
const PAGE_SIZE = 50;

export function ActivityLogDock({ symbol }: { symbol: string }) {
  const [entries, setEntries] = useState<LogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [levelFilter, setLevelFilter] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    function fetchOnce() {
      getActivityLog({ q: symbol, level: levelFilter || undefined, limit: PAGE_SIZE })
        .then(({ items }) => {
          if (cancelled) return;
          setEntries(items);
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          setEntries([]);
          setError(e instanceof ApiError ? e.message : "failed to load activity log");
        });
    }

    fetchOnce();
    if (!live) return () => {
      cancelled = true;
    };
    const id = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, levelFilter, live]);

  return (
    <div className="border-b border-line bg-panel">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-1.5">
        <span className="text-xs font-medium text-ink">Activity log — {symbol}</span>
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink"
        >
          <option value="">All levels</option>
          <option value="INFO">Info</option>
          <option value="WARNING">Warning</option>
          <option value="ERROR">Error</option>
        </select>
        <label className="flex items-center gap-1.5 text-xs text-ink-muted">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Watch live
        </label>
        <Link href="/logs" className="ml-auto text-xs text-ink-muted hover:text-accent">
          Full history →
        </Link>
      </div>
      <div className="max-h-56 overflow-y-auto">
        {error && <p className="px-3 py-2 text-xs text-err">{error}</p>}
        {!error && entries === null && (
          <p className="px-3 py-2 text-xs text-ink-muted">Loading…</p>
        )}
        {!error && entries !== null && entries.length === 0 && (
          <p className="px-3 py-2 text-xs text-ink-muted">
            No activity for {symbol} yet — signals, vetoes, and fills will show up here.
          </p>
        )}
        {!error && entries !== null && entries.length > 0 && (
          <ul className="divide-y divide-line text-xs">
            {entries.map((e) => (
              <li key={e.id} className="flex items-start gap-2 px-3 py-1.5">
                <span className="shrink-0 whitespace-nowrap text-ink-muted">
                  {formatTime(e.created_at)}
                </span>
                <span className={`shrink-0 font-medium ${levelTone(e.level)}`}>{e.level}</span>
                <span className="font-mono text-ink">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function levelTone(level: string): string {
  if (level === "ERROR" || level === "CRITICAL") return "text-err";
  if (level === "WARNING") return "text-accent";
  return "text-ink-muted";
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(11, 19);
}
