'use client';

/**
 * Split-window chart layout (§): up to 4 chart windows on screen at once, all
 * showing the same symbol. Window 1 is always the full ChartPanel — drawing
 * tools, indicators dock, order popovers, trade placement, backtest/live-bot
 * overlay, everything unchanged from the single-chart view. Windows 2-4 are
 * lightweight MiniChartPanels (candles + volume + trade markers only) with
 * their own independent timeframe, so this is a multi-timeframe layout
 * (TradingView-style), not 4 independent charts — see the frontend-feature
 * skill conversation this was scoped from.
 *
 * Replay sync: only the primary window drives entering/exiting replay,
 * playing, and seeking (its existing ReplayControls/SessionReplayPicker UI,
 * untouched). This component just mirrors that window's replay session
 * (`onReplaySessionChange`/`onReplayCursorTime`, added to ChartPanel for
 * this feature) into `sharedReplay` state, which every MiniChartPanel reads
 * to fetch the same period at its own timeframe and clip its display to the
 * same cursor position. A backtest-report replay (no explicit from/to) has
 * nothing for secondary windows to sync to — they just fall back to their
 * own live view in that case, same as when replay is off entirely.
 */

import { Columns2, Grid2x2, Square } from 'lucide-react';
import { useState, type ComponentProps } from 'react';
import type { Candle } from '@/shared/api/client';
import { isTimeframe } from './chartFormat';
import { ChartPanel } from './ChartPanel';
import { MiniChartPanel } from './MiniChartPanel';
import type { SharedReplaySession } from './types';

const WINDOW_COUNT_KEY = 'tb.chartWindowCount';
const WINDOW_TIMEFRAMES_KEY = 'tb.chartWindowTimeframes';
const MAX_WINDOWS = 4;
// Distinct default timeframes for windows 2-4 so a first-time split shows
// genuinely different views rather than three identical M5 charts.
const DEFAULT_SECONDARY_TIMEFRAMES: Candle['timeframe'][] = ['M15', 'H1', 'H4'];

function loadWindowCount(): number {
  try {
    const stored = Number(localStorage.getItem(WINDOW_COUNT_KEY));
    return stored >= 1 && stored <= MAX_WINDOWS ? stored : 1;
  } catch {
    return 1;
  }
}

function loadWindowTimeframes(): Candle['timeframe'][] {
  try {
    const raw = localStorage.getItem(WINDOW_TIMEFRAMES_KEY);
    if (!raw) return DEFAULT_SECONDARY_TIMEFRAMES;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return DEFAULT_SECONDARY_TIMEFRAMES;
    return DEFAULT_SECONDARY_TIMEFRAMES.map((fallback, i) =>
      isTimeframe(parsed[i]) ? parsed[i] : fallback,
    );
  } catch {
    return DEFAULT_SECONDARY_TIMEFRAMES;
  }
}

function saveWindowTimeframes(timeframes: Candle['timeframe'][]) {
  try {
    localStorage.setItem(WINDOW_TIMEFRAMES_KEY, JSON.stringify(timeframes));
  } catch {
    // Ignore blocked/full localStorage — timeframes just won't persist.
  }
}

type ChartPanelProps = ComponentProps<typeof ChartPanel>;

// Grid arrangement per window count — 3 gives the primary window the full
// left column (its toolbars need more width than a mini window) with the
// two secondary windows stacked to the right, matching common multi-chart
// layout presets rather than an uneven 3-equal-column split.
const GRID_CLASS: Record<number, string> = {
  1: 'grid-cols-1 grid-rows-1',
  2: 'grid-cols-2 grid-rows-1',
  3: 'grid-cols-2 grid-rows-2',
  4: 'grid-cols-2 grid-rows-2',
};

export function MultiChartLayout(props: ChartPanelProps) {
  const [windowCount, setWindowCount] = useState(loadWindowCount);
  const [secondaryTimeframes, setSecondaryTimeframes] = useState(loadWindowTimeframes);
  const [sharedReplay, setSharedReplay] = useState<SharedReplaySession | null>(null);

  function setCount(count: number) {
    setWindowCount(count);
    try {
      localStorage.setItem(WINDOW_COUNT_KEY, String(count));
    } catch {
      // Ignore blocked/full localStorage — window count just won't persist.
    }
  }

  function setSecondaryTimeframe(slot: number, tf: Candle['timeframe']) {
    const updated = secondaryTimeframes.map((t, i) => (i === slot ? tf : t));
    setSecondaryTimeframes(updated);
    saveWindowTimeframes(updated);
  }

  // Removes this specific window's slot (not just the last one) so closing
  // window 2 out of {2,3,4} leaves {3,4} on screen, not {2,3} — the other
  // open windows' timeframes/positions shouldn't shuffle just because a
  // different one closed.
  function closeSecondaryWindow(slot: number) {
    const remaining = secondaryTimeframes.filter((_, i) => i !== slot);
    const padded = [...remaining, DEFAULT_SECONDARY_TIMEFRAMES[remaining.length] ?? 'M15'];
    setSecondaryTimeframes(padded);
    saveWindowTimeframes(padded);
    setCount(Math.max(1, windowCount - 1));
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-1">
        <button
          onClick={() => setCount(1)}
          title="Single chart"
          className={`cursor-pointer rounded border p-1 ${
            windowCount === 1 ? 'border-accent text-accent' : 'border-line text-ink-muted hover:text-accent'
          }`}
        >
          <Square size={14} />
        </button>
        <button
          onClick={() => setCount(2)}
          title="Split into 2 windows"
          className={`cursor-pointer rounded border p-1 ${
            windowCount === 2 ? 'border-accent text-accent' : 'border-line text-ink-muted hover:text-accent'
          }`}
        >
          <Columns2 size={14} />
        </button>
        <button
          onClick={() => setCount(3)}
          title="Split into 3 windows"
          className={`cursor-pointer rounded border px-1.5 py-1 text-[10px] font-bold ${
            windowCount === 3 ? 'border-accent text-accent' : 'border-line text-ink-muted hover:text-accent'
          }`}
        >
          3
        </button>
        <button
          onClick={() => setCount(4)}
          title="Split into 4 windows"
          className={`cursor-pointer rounded border p-1 ${
            windowCount === 4 ? 'border-accent text-accent' : 'border-line text-ink-muted hover:text-accent'
          }`}
        >
          <Grid2x2 size={14} />
        </button>
      </div>

      <div className={`grid min-h-0 flex-1 gap-2 ${GRID_CLASS[windowCount]}`}>
        <div className={windowCount === 3 ? 'row-span-2 flex min-w-0 min-h-0' : 'flex min-w-0 min-h-0'}>
          <ChartPanel
            {...props}
            onReplaySessionChange={(session) => setSharedReplay({ ...session, cursorTime: null })}
            onReplayCursorTime={(time) =>
              setSharedReplay((prev) => (prev ? { ...prev, cursorTime: time } : prev))
            }
          />
        </div>
        {Array.from({ length: windowCount - 1 }, (_, i) => (
          <MiniChartPanel
            key={i}
            symbol={props.symbol}
            timeframe={secondaryTimeframes[i] ?? DEFAULT_SECONDARY_TIMEFRAMES[i]}
            onTimeframeChange={(tf) => setSecondaryTimeframe(i, tf)}
            sharedReplay={sharedReplay}
            onClose={() => closeSecondaryWindow(i)}
          />
        ))}
      </div>
    </div>
  );
}
