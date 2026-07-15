"use client";

/**
 * ReplayControls — the "live session" player for a backtest report: play,
 * pause, step forward/backward one bar, playback speed, and a scrubber over
 * the loaded candle window. Purely presentational — ChartPanel owns the
 * cursor state, the candle/marker/drawing gating, and the autoplay loop;
 * this component only renders controls and reports intent via callbacks.
 *
 * Docked below the chart header, same slot/style as IndicatorsDock/
 * ActivityLogDock, shown while ChartPanel's `replayActive` is true.
 */

import { ChevronsLeft, ChevronsRight, Crosshair, Pause, Play } from "lucide-react";

const SPEED_OPTIONS = [0.25, 0.5, 1, 2, 4, 8, 16];

export function ReplayControls({
  playing,
  onPlayPause,
  onStepBack,
  onStepForward,
  speed,
  onSpeedChange,
  cursorIndex,
  totalBars,
  currentTime,
  onSeek,
  following,
  onRecenter,
}: {
  playing: boolean;
  onPlayPause: () => void;
  onStepBack: () => void;
  onStepForward: () => void;
  speed: number;
  onSpeedChange: (speed: number) => void;
  cursorIndex: number;
  totalBars: number;
  /** Formatted label for the cursor bar's time, e.g. "2026-07-14 09:35:00". */
  currentTime: string;
  onSeek: (index: number) => void;
  /** Whether the chart is currently auto-centering on the cursor bar — off
   * once the user drags/zooms manually, back on via the button below. */
  following: boolean;
  onRecenter: () => void;
}) {
  const atStart = cursorIndex <= 0;
  const atEnd = cursorIndex >= totalBars - 1;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-3 py-1.5 text-xs">
      <button
        className="flex cursor-pointer items-center justify-center rounded border border-line p-1 text-ink hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink"
        onClick={onStepBack}
        disabled={atStart}
        title="Step back one bar"
      >
        <ChevronsLeft size={14} />
      </button>
      <button
        className="flex cursor-pointer items-center gap-1 rounded border border-accent px-2 py-0.5 text-accent hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
        onClick={onPlayPause}
        disabled={atEnd && !playing}
        title={playing ? "Pause" : "Play"}
      >
        {playing ? (
          <>
            <Pause size={14} fill="currentColor" /> Pause
          </>
        ) : (
          <>
            <Play size={14} fill="currentColor" /> Play
          </>
        )}
      </button>
      <button
        className="flex cursor-pointer items-center justify-center rounded border border-line p-1 text-ink hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink"
        onClick={onStepForward}
        disabled={atEnd}
        title="Step forward one bar"
      >
        <ChevronsRight size={14} />
      </button>
      <label className="flex items-center gap-1.5 text-ink-muted">
        Speed
        <select
          value={speed}
          onChange={(e) => onSpeedChange(Number(e.target.value))}
          className="cursor-pointer rounded border border-line bg-panel px-1.5 py-1 text-ink"
        >
          {SPEED_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}x
            </option>
          ))}
        </select>
      </label>
      <input
        type="range"
        min={0}
        max={Math.max(0, totalBars - 1)}
        value={cursorIndex}
        onChange={(e) => onSeek(Number(e.target.value))}
        className="mx-1 min-w-24 flex-1 cursor-pointer"
        title="Seek to bar"
      />
      <span className="shrink-0 whitespace-nowrap text-ink-muted">
        bar {cursorIndex + 1}/{totalBars} · {currentTime}
      </span>
      <button
        className={`flex shrink-0 cursor-pointer items-center gap-1 rounded border px-2 py-0.5 ${
          following
            ? 'border-line text-ink-muted'
            : 'border-accent text-accent hover:bg-accent/20'
        }`}
        onClick={onRecenter}
        disabled={following}
        title={
          following
            ? 'Following the current bar'
            : 'Panned away — click to re-center on the current bar'
        }
      >
        <Crosshair size={14} />
        {following ? 'Centered' : 'Center'}
      </button>
    </div>
  );
}
