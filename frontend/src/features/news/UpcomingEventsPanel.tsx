"use client";

import { useEffect, useState } from "react";
import {
  getActiveNewsWindows,
  getUpcomingNews,
  type NewsEvent,
  type NewsWindow,
} from "@/shared/api/client";
import { StatusBadge } from "@/features/strategies/StatusBadge";

const POLL_MS = 30_000; // matches the backend's news-window transition-check cadence

/** Upcoming economic calendar + any currently active news window (§6.7, §8).
 * Read-only — the engine reacts to windows on its own via `NewsSkillSelector`
 * and the trade engine's pre-news flatten; this just shows what it's doing. */
export function UpcomingEventsPanel() {
  const [events, setEvents] = useState<NewsEvent[] | null>(null);
  const [windows, setWindows] = useState<NewsWindow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      Promise.all([getUpcomingNews(), getActiveNewsWindows()])
        .then(([e, w]) => {
          if (cancelled) return;
          setEvents(e);
          setWindows(w);
          setError(null);
        })
        .catch(() => {
          if (!cancelled) setError("failed to load news calendar");
        });
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="flex flex-col gap-4 p-4">
      {error && <p className="text-sm text-err">{error}</p>}

      <section>
        <h2 className="mb-2 text-sm font-bold text-ink-muted">Active news windows</h2>
        {windows === null ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : windows.length === 0 ? (
          <p className="text-sm text-ink-muted">
            None active — trading follows the normal per-symbol skill.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {windows.map((w) => (
              <li
                key={`${w.event.name}-${w.window_start}`}
                className="flex items-center gap-2 rounded-md border border-line bg-panel p-3 text-sm"
              >
                <StatusBadge status={w.phase} />
                <span className="font-medium">{w.event.name}</span>
                <span className="text-ink-muted">skill: {w.skill}</span>
                <span className="ml-auto text-ink-muted">{formatTime(w.event.time)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-bold text-ink-muted">Upcoming events</h2>
        {events === null ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-ink-muted">Nothing in the next 7 days.</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line bg-panel">
            <table className="w-full min-w-[520px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-muted">
                  <th className="px-3 py-2 font-medium">Event</th>
                  <th className="px-3 py-2 font-medium">Currency</th>
                  <th className="px-3 py-2 font-medium">Impact</th>
                  <th className="px-3 py-2 font-medium">Time</th>
                  <th className="px-3 py-2 font-medium">Skill</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr
                    key={`${e.name}-${e.time}`}
                    className="border-b border-line last:border-0 hover:bg-bg/40"
                  >
                    <td className="px-3 py-2">{e.name}</td>
                    <td className="px-3 py-2 text-ink-muted">{e.currency}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={e.impact} />
                    </td>
                    <td className="px-3 py-2 text-ink-muted">{formatTime(e.time)}</td>
                    <td className="px-3 py-2 text-ink-muted">{e.skill ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}
