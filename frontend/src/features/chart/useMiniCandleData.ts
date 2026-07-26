'use client';

/**
 * Candle data for a secondary chart window (multi-chart layout, split-window
 * §): a trimmed-down sibling of useCandleData.ts for MiniChartPanel — same
 * live fetch + WS subscribe for the normal view, but none of the drawing/
 * indicator/backtest/pagination machinery a secondary window doesn't have.
 *
 * Replay sync: when the primary window's `sharedReplay.active` is true and
 * it has an explicit `sessionPeriod` (session replay, not a backtest-report
 * replay — see SharedReplaySession's doc comment), this hook fetches that
 * same period at its own timeframe via `fetchCandlesForPeriod` (reused from
 * useCandleData.ts) once, then clips the displayed candles to
 * `sharedReplay.cursorTime` as it advances — no live WS subscription while
 * replaying, mirroring the primary window's own behavior.
 */

import { useEffect, useRef, useState } from 'react';
import { getCandles, type Candle } from '@/shared/api/client';
import { onSocketConnect, subscribeRoom } from '@/shared/api/ws';
import { isCandleMessage } from './chartData';
import { fetchCandlesForPeriod } from './useCandleData';
import type { SharedReplaySession } from './types';

const MINI_CANDLE_COUNT = 300;

export interface UseMiniCandleDataParams {
  accountId: string | null;
  symbol: string;
  timeframe: Candle['timeframe'];
  sharedReplay: SharedReplaySession | null;
}

export function useMiniCandleData(params: UseMiniCandleDataParams) {
  const { accountId, symbol, timeframe, sharedReplay } = params;
  const replaying = !!(sharedReplay?.active && sharedReplay.sessionPeriod);
  const sessionFrom = sharedReplay?.sessionPeriod?.from ?? null;
  const sessionTo = sharedReplay?.sessionPeriod?.to ?? null;

  // Full period loaded during replay, or the live-fetched window otherwise —
  // sliced down to `visibleCandles` below for the cursor-gated replay view.
  const allCandlesRef = useRef<Candle[]>([]);
  const [visibleCandles, setVisibleCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Loads history — either the live "now" window (normal view) or the whole
  // shared-replay period (once per symbol/timeframe/period, not per cursor
  // tick) — and subscribes to live WS updates only in the normal view.
  useEffect(() => {
    if (!accountId) return;
    const account = accountId;
    let cancelled = false;
    setError(null);
    setLoading(true);

    if (replaying && sessionFrom !== null && sessionTo !== null) {
      fetchCandlesForPeriod(account, symbol, timeframe, sessionFrom, sessionTo)
        .then((candles) => {
          if (cancelled) return;
          allCandlesRef.current = candles;
          setVisibleCandles(candles);
          setLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          setError('failed to load session replay candles');
          setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }

    getCandles(account, symbol, timeframe, MINI_CANDLE_COUNT)
      .then((candles) => {
        if (cancelled) return;
        allCandlesRef.current = candles;
        setVisibleCandles(candles);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError('failed to load candles');
        setLoading(false);
      });

    const unsubscribe = subscribeRoom(
      ['candle_closed', 'candle_update'],
      { accountId, symbol, timeframe },
      (message) => {
        if (!isCandleMessage(message)) return;
        const { candle } = message;
        const bars = allCandlesRef.current;
        const lastTime = bars.length > 0 ? bars[bars.length - 1].time : undefined;
        if (lastTime !== undefined && candle.time < lastTime) return;
        const updated =
          lastTime === candle.time
            ? [...bars.slice(0, -1), candle]
            : [...bars, candle];
        allCandlesRef.current = updated;
        setVisibleCandles(updated);
      },
    );

    // Reconnect gap fill — same rationale as useCandleData's own patch: WS
    // deltas never backfill what was missed while disconnected.
    const unsubscribeReconnect = onSocketConnect(() => {
      if (cancelled) return;
      getCandles(account, symbol, timeframe, MINI_CANDLE_COUNT)
        .then((latest) => {
          if (cancelled || latest.length === 0) return;
          const cutoff = latest[0].time;
          const merged = [
            ...allCandlesRef.current.filter((c) => c.time < cutoff),
            ...latest,
          ];
          allCandlesRef.current = merged;
          setVisibleCandles(merged);
        })
        .catch(() => {
          // Transient failure — the next reconnect or live tick catches up.
        });
    });

    return () => {
      cancelled = true;
      unsubscribe();
      unsubscribeReconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, symbol, timeframe, replaying, sessionFrom, sessionTo]);

  // Clip to the shared replay cursor — runs on every cursor tick, cheap
  // (a linear scan over one timeframe's worth of an already-loaded period).
  useEffect(() => {
    if (!replaying) return;
    const cursorTime = sharedReplay?.cursorTime;
    if (cursorTime === null || cursorTime === undefined) return;
    const all = allCandlesRef.current;
    let index = all.findIndex((c) => (c.time as number) > cursorTime);
    if (index === -1) index = all.length;
    setVisibleCandles(all.slice(0, index));
  }, [replaying, sharedReplay?.cursorTime]);

  return { visibleCandles, loading, error, replaying };
}

export type MiniCandleData = ReturnType<typeof useMiniCandleData>;
