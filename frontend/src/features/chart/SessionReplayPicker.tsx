'use client';

/**
 * SessionReplayPicker — date/time range picker for entering "session
 * replay" mode (an arbitrary historical period replayed bar-by-bar, like a
 * live session, independent of any saved backtest report). Purely
 * presentational — ChartPanel owns the input strings, the estimate/warning
 * thresholds, and the chunked fetch; this only renders the form and reports
 * intent via callbacks.
 *
 * Docked below the chart header, same slot/style as ReplayControls/
 * IndicatorsDock, shown while ChartPanel's `showSessionReplayPicker` is true.
 */

import { AlertTriangle } from 'lucide-react';

export function SessionReplayPicker({
  fromValue,
  toValue,
  onFromChange,
  onToChange,
  estimate,
  onCancel,
  onStart,
}: {
  fromValue: string;
  toValue: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  /** null while the range is incomplete/invalid (blank field, or `to` not
   * after `from`) — disables the Start button. */
  estimate: {
    candles: number;
    pages: number;
    level: 'ok' | 'warn' | 'block';
  } | null;
  onCancel: () => void;
  onStart: () => void;
}) {
  const canStart = estimate !== null && estimate.level !== 'block';

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-1.5 text-xs">
      <label className="flex items-center gap-1.5 text-ink-muted">
        From
        <input
          type="datetime-local"
          value={fromValue}
          onChange={(e) => onFromChange(e.target.value)}
          className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-ink"
        />
      </label>
      <label className="flex items-center gap-1.5 text-ink-muted">
        To
        <input
          type="datetime-local"
          value={toValue}
          onChange={(e) => onToChange(e.target.value)}
          className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-ink"
        />
      </label>
      {estimate && (
        <span
          className={`flex items-center gap-1 ${
            estimate.level === 'block'
              ? 'text-err'
              : estimate.level === 'warn'
                ? 'text-accent'
                : 'text-ink-muted'
          }`}
        >
          {estimate.level !== 'ok' && <AlertTriangle size={12} />}
          ~{estimate.candles.toLocaleString()} candles
          {estimate.pages > 1 && ` (${estimate.pages} requests)`}
          {estimate.level === 'warn' &&
            ' — long period, may take a while to load'}
          {estimate.level === 'block' &&
            ' — too long, pick a shorter period or a larger timeframe'}
        </span>
      )}
      <button
        className="flex cursor-pointer items-center gap-1 rounded border border-accent px-2 py-0.5 text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
        onClick={onStart}
        disabled={!canStart}
        title={
          canStart
            ? 'Fetch this period and start replaying it'
            : 'Pick a valid from/to range first'
        }
      >
        Start replay
      </button>
      <button
        className="cursor-pointer rounded border border-line px-2 py-0.5 text-ink-muted hover:border-accent hover:text-accent"
        onClick={onCancel}
      >
        Cancel
      </button>
    </div>
  );
}
