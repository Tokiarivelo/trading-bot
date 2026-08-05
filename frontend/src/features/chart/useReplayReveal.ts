'use client';

/**
 * Transient "reveal" flashes for bot-session replay (BOT_SESSION_REPLAY_PLAN
 * phase 3).
 *
 * Watches the replay cursor and, each time it advances past a trade's
 * `open_time`/`close_time` or a non-`opened` signal's `time`, emits a short
 * lived `ReplayRevealEvent` that `ReplayRevealOverlay` paints on the chart as
 * a blinking "BUY HERE" / "SELL HERE" / "EXIT HERE" label.
 *
 * Deliberately narrow: it owns nothing but the active event list and its
 * expiry timers — no fetching, no chart access, no marker drawing (markers
 * stay in useBacktestData's marker effect, which already gates them by the
 * same cursor). It is completely inert while `replayActive` is false: the
 * effect returns immediately and the event list stays the same empty array,
 * so consumers never re-render because of it.
 *
 * Cheapness note: the only state here is `events`, which changes when a bar
 * actually reveals something and again when that flash expires — *not* once
 * per animation frame. The intra-bar tick-form cursor is a ref elsewhere and
 * never reaches this hook.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type {
  BacktestSignal,
  BacktestTrade,
  Candle,
} from '@/shared/api/client';
import type { ReplayRevealEvent } from './types';

/** How long a flash stays on screen before it removes itself. */
const REVEAL_TTL_MS = 2500;
/** Hard cap on simultaneously visible flashes, so a coarse cursor step that
 * crosses many events at once can't paper the chart over. Newest win. */
const MAX_ACTIVE_REVEALS = 6;

export interface UseReplayRevealParams {
  /** ChartPanel's `replayActive`. False ⇒ the hook does nothing at all. */
  replayActive: boolean;
  /** The cursor bar's epoch-seconds time (`useBacktestData.replayCursorTime`),
   * null when not replaying. */
  replayCursorTime: number | null;
  /** The eyed bot's / report's signals — same array the markers use. */
  signals: BacktestSignal[] | null;
  /** The eyed bot's / report's trades — same array the markers use. */
  trades: BacktestTrade[] | null;
  /** Loaded candles, read only to resolve a price for signal flashes (a
   * `BacktestSignal` carries no price of its own). */
  candlesRef: RefObject<Candle[]>;
}

const EMPTY_EVENTS: ReplayRevealEvent[] = [];

/** Close of the last loaded candle at or before `time`, or null. */
function priceAtTime(candles: Candle[], time: number): number | null {
  for (let i = candles.length - 1; i >= 0; i -= 1) {
    if ((candles[i].time as number) <= time) return candles[i].close;
  }
  return null;
}

export function useReplayReveal({
  replayActive,
  replayCursorTime,
  signals,
  trades,
  candlesRef,
}: UseReplayRevealParams) {
  const [events, setEvents] = useState<ReplayRevealEvent[]>(EMPTY_EVENTS);
  /** Cursor time the previous run already emitted for; null = nothing seen
   * yet this session (the first observed cursor position is a baseline, not
   * a reveal, otherwise entering replay would flash the whole prefix). */
  const lastCursorRef = useRef<number | null>(null);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const seqRef = useRef(0);

  const clearAll = useCallback(() => {
    timersRef.current.forEach((t) => clearTimeout(t));
    timersRef.current.clear();
    setEvents((prev) => (prev.length === 0 ? prev : EMPTY_EVENTS));
  }, []);

  // Leaving replay wipes everything and forgets the cursor baseline, so the
  // next session starts clean instead of replaying stale deltas.
  useEffect(() => {
    if (replayActive) return;
    lastCursorRef.current = null;
    clearAll();
  }, [replayActive, clearAll]);

  useEffect(() => {
    if (!replayActive || replayCursorTime === null) return;

    const prev = lastCursorRef.current;
    lastCursorRef.current = replayCursorTime;

    // Baseline frame (just entered replay): nothing to reveal yet.
    if (prev === null) return;
    // A signals/trades poll re-ran this effect without the cursor moving —
    // keep whatever is currently blinking, emit nothing.
    if (replayCursorTime === prev) return;
    // Seeked backwards: the flashes on screen refer to a future that no
    // longer happened. Drop them and re-baseline.
    if (replayCursorTime < prev) {
      clearAll();
      return;
    }

    const fresh: ReplayRevealEvent[] = [];
    const crossed = (t: number) => t > prev && t <= replayCursorTime;
    const nextId = () => {
      seqRef.current += 1;
      return `reveal-${seqRef.current}`;
    };

    for (const t of trades ?? []) {
      if (crossed(t.open_time)) {
        fresh.push({
          id: nextId(),
          time: t.open_time,
          price: t.open_price,
          kind: t.side,
          label: t.side === 'buy' ? 'BUY HERE' : 'SELL HERE',
        });
      }
      if (crossed(t.close_time)) {
        fresh.push({
          id: nextId(),
          time: t.close_time,
          price: t.close_price,
          kind: 'exit',
          label: t.profit >= 0 ? 'EXIT — WIN' : 'EXIT — LOSS',
        });
      }
    }

    for (const s of signals ?? []) {
      // 'opened' signals are already covered by their trade's entry flash.
      if (s.outcome === 'opened') continue;
      if (!crossed(s.time)) continue;
      fresh.push({
        id: nextId(),
        time: s.time,
        price: priceAtTime(candlesRef.current, s.time),
        kind: 'rejected',
        label: s.direction === 'buy' ? 'BUY REJECTED' : 'SELL REJECTED',
      });
    }

    if (fresh.length === 0) return;

    setEvents((current) =>
      [...current, ...fresh].slice(-MAX_ACTIVE_REVEALS),
    );
    for (const e of fresh) {
      const timer = setTimeout(() => {
        timersRef.current.delete(e.id);
        setEvents((current) => current.filter((x) => x.id !== e.id));
      }, REVEAL_TTL_MS);
      timersRef.current.set(e.id, timer);
    }
    // `clearAll` is stable; candlesRef is a stable ref object.
  }, [replayActive, replayCursorTime, signals, trades, candlesRef, clearAll]);

  // Unmount: never leave expiry timers behind.
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((t) => clearTimeout(t));
      timers.clear();
    };
  }, []);

  return events;
}

export type ReplayReveal = ReturnType<typeof useReplayReveal>;
