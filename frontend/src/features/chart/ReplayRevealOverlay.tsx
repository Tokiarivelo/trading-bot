'use client';

/**
 * Blinking "BUY HERE" / "SELL HERE" / exit labels shown while a bot session
 * replays (BOT_SESSION_REPLAY_PLAN phase 3). Purely presentational: it takes
 * the transient events from `useReplayReveal` and places each one over the
 * chart via `timeToCoordinate`/`priceToCoordinate`, exactly like the other
 * absolutely-positioned overlays in ChartPanel.tsx (see `ZoneInfoPopover`).
 *
 * Renders `null` — and subscribes to nothing — whenever there are no active
 * events, which is always the case outside replay.
 */

import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import { memo, useEffect, useState } from 'react';
import type { RefObject } from 'react';
import type { ReplayRevealEvent } from './types';

export interface ReplayRevealOverlayProps {
  /** Currently visible reveal events (`useReplayReveal`'s return). */
  events: ReplayRevealEvent[];
  chartRef: RefObject<IChartApi | null>;
  candleSeriesRef: RefObject<ISeriesApi<'Candlestick'> | null>;
}

/** Colour + vertical offset per event kind. Tokens only (`@theme` in
 * globals.css) — no raw hex. Entries sit under the bar, exits/rejections
 * above it, mirroring how the trade markers are placed. */
const KIND_STYLE: Record<
  ReplayRevealEvent['kind'],
  { box: string; above: boolean }
> = {
  buy: {
    box: 'border-buy bg-buy/20 text-buy',
    above: false,
  },
  sell: {
    box: 'border-sell bg-sell/20 text-sell',
    above: true,
  },
  exit: {
    box: 'border-accent bg-accent/20 text-ink',
    above: true,
  },
  rejected: {
    box: 'border-err bg-err/20 text-err',
    above: true,
  },
};

export const ReplayRevealOverlay = memo(function ReplayRevealOverlay({
  events,
  chartRef,
  candleSeriesRef,
}: ReplayRevealOverlayProps) {
  const hasEvents = events.length > 0;
  // Labels are anchored to chart coordinates, so they must be repositioned
  // when the user pans/zooms. Only subscribed while something is showing, so
  // this costs nothing outside replay.
  const [, setRepositionTick] = useState(0);
  useEffect(() => {
    const chart = chartRef.current;
    if (!hasEvents || !chart) return;
    const timeScale = chart.timeScale();
    const onRangeChange = () => setRepositionTick((t) => t + 1);
    timeScale.subscribeVisibleLogicalRangeChange(onRangeChange);
    return () =>
      timeScale.unsubscribeVisibleLogicalRangeChange(onRangeChange);
  }, [hasEvents, chartRef]);

  const chart = chartRef.current;
  const series = candleSeriesRef.current;
  if (!hasEvents || !chart || !series) return null;

  const timeScale = chart.timeScale();

  return (
    <>
      {events.map((e) => {
        if (e.price === null) return null;
        const x = timeScale.timeToCoordinate(e.time as UTCTimestamp);
        const y = series.priceToCoordinate(e.price);
        if (x === null || y === null) return null;
        const style = KIND_STYLE[e.kind];
        return (
          <div
            key={e.id}
            className='pointer-events-none absolute z-30 flex flex-col items-center'
            style={{
              left: `${x}px`,
              top: `${y}px`,
              transform: style.above
                ? 'translate(-50%, -160%)'
                : 'translate(-50%, 60%)',
            }}
          >
            <span
              className={`animate-pulse rounded border px-1.5 py-0.5 text-[10px] font-bold tracking-wide whitespace-nowrap shadow-lg ${style.box}`}
            >
              {e.label}
            </span>
          </div>
        );
      })}
    </>
  );
});
