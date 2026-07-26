'use client';

/**
 * Ref-counted shared poller — same pattern as `shared/api/ws.ts`'s
 * ref-counted room subscriptions, applied to plain HTTP polling. A
 * multi-window chart layout can have up to 4 `ChartPanel` instances open on
 * the same symbol at once, each previously running its own independent
 * `setInterval` for the spread/symbol-info poll, the news-window poll, and
 * the trade-markers poll — 4x the identical requests to the same endpoint
 * every tick. Callers sharing a `key` (e.g. `${accountId}:${symbol}`) get one
 * fetch loop; the last unsubscribe tears it down.
 */

interface PollEntry<T> {
  data: T | undefined;
  error: unknown;
  hasResult: boolean;
  listeners: Set<(data: T | undefined, error: unknown) => void>;
  timer: ReturnType<typeof setInterval>;
}

const pollers = new Map<string, PollEntry<unknown>>();

/** Subscribes `onUpdate` to a shared poll loop for `key`, starting it (and
 * firing an immediate fetch) if this is the first subscriber, or handing a
 * late subscriber the last known result right away instead of leaving it
 * waiting up to `intervalMs` for the next tick. Returns an unsubscribe fn;
 * the loop itself stops once the last subscriber for `key` leaves. */
export function subscribeSharedPoll<T>(
  key: string,
  intervalMs: number,
  fetchFn: () => Promise<T>,
  onUpdate: (data: T | undefined, error: unknown) => void,
): () => void {
  let entry = pollers.get(key) as PollEntry<T> | undefined;
  if (!entry) {
    const newEntry: PollEntry<T> = {
      data: undefined,
      error: null,
      hasResult: false,
      listeners: new Set(),
      timer: undefined as unknown as ReturnType<typeof setInterval>,
    };
    const run = () => {
      fetchFn()
        .then((data) => {
          newEntry.data = data;
          newEntry.error = null;
          newEntry.hasResult = true;
          for (const listener of newEntry.listeners) listener(data, null);
        })
        .catch((error: unknown) => {
          newEntry.data = undefined;
          newEntry.error = error;
          newEntry.hasResult = true;
          for (const listener of newEntry.listeners) listener(undefined, error);
        });
    };
    newEntry.timer = setInterval(run, intervalMs);
    pollers.set(key, newEntry as PollEntry<unknown>);
    entry = newEntry;
    run();
  } else if (entry.hasResult) {
    queueMicrotask(() => onUpdate(entry!.data, entry!.error));
  }

  entry.listeners.add(onUpdate);
  return () => {
    const current = pollers.get(key) as PollEntry<T> | undefined;
    if (!current) return;
    current.listeners.delete(onUpdate);
    if (current.listeners.size === 0) {
      clearInterval(current.timer);
      pollers.delete(key);
    }
  };
}
