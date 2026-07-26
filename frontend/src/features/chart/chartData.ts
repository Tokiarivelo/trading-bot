import type { UTCTimestamp } from 'lightweight-charts';
import type { Candle } from '@/shared/api/client';

export function toBar(candle: Candle) {
  return {
    time: candle.time as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  };
}

export function toVolumeBar(candle: Candle, upColor: string, downColor: string) {
  return {
    time: candle.time as UTCTimestamp,
    value: candle.tick_volume,
    color: candle.close >= candle.open ? upColor : downColor,
  };
}

export function isCandleMessage(
  message: unknown,
): message is { type: 'candle_closed' | 'candle_update'; candle: Candle } {
  const type = (message as { type?: unknown } | null)?.type;
  return type === 'candle_closed' || type === 'candle_update';
}

/** Buckets items sharing the same key, preserving first-seen key order —
 * used to collapse same-time/same-side entry markers (many trades opening on
 * one candle previously stacked one arrow+label per trade, unreadable once
 * more than a couple landed on the same bar) into a single arrow with a
 * "×N" count badge instead. */
export function groupByKey<T>(items: T[], keyOf: (item: T) => string): T[][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const key = keyOf(item);
    const group = groups.get(key);
    if (group) group.push(item);
    else groups.set(key, [item]);
  }
  return [...groups.values()];
}

/** `lightweight-charts-drawing`'s anchors call the chart's native
 * `timeToCoordinate`, which returns null (silently skipping the draw) unless
 * the time exactly matches a loaded bar's timestamp. Backtest trades always
 * open/close exactly on a candle close, so they match already — but a live
 * trade's open/close time is the broker's real fill timestamp, essentially
 * never aligned to a bar boundary on any timeframe. Snap it to the nearest
 * loaded candle so the anchor resolves to a real coordinate. `candles` is
 * ascending by time (see `candlesRef`). */
export function nearestCandleTime(
  candles: Candle[],
  target: number,
): UTCTimestamp | null {
  if (candles.length === 0) return null;
  let lo = 0;
  let hi = candles.length - 1;
  if (target <= candles[lo].time) return candles[lo].time as UTCTimestamp;
  if (target >= candles[hi].time) return candles[hi].time as UTCTimestamp;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (candles[mid].time < target) lo = mid + 1;
    else hi = mid;
  }
  const after = candles[lo];
  const before = candles[Math.max(0, lo - 1)];
  return (
    target - before.time <= after.time - target ? before.time : after.time
  ) as UTCTimestamp;
}
