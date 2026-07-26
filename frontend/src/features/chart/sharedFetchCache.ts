'use client';

/**
 * One-shot shared fetch dedup — the single-promise analogue of
 * `sharedPoll.ts`'s ref-counted recurring poller (and `shared/api/ws.ts`'s
 * room subscriptions). During a synced multi-window replay, several coarser
 * follower windows can independently need the *same* finer-timeframe candles
 * for the same session period: e.g. an M5 and an M15 follower alongside an M1
 * master both aggregate their forming bar from that master's M1 candles over
 * the identical from/to window. Without dedup each window fires its own
 * (potentially multi-page) `fetchCandlesForPeriod` for byte-identical data.
 * Callers sharing a `key` (e.g. `${accountId}:${symbol}:${masterTf}:${from}:${to}`)
 * get one in-flight/resolved promise instead. Unlike `sharedPoll.ts` there's
 * no interval to tear down — the promise is cached for the session; a failed
 * fetch is evicted so a later caller can retry rather than inheriting the
 * rejection.
 */

const cache = new Map<string, Promise<unknown>>();

/** Returns the shared promise for `key`, starting `fetchFn` only if no entry
 * exists yet. A rejected fetch is removed from the cache so the next caller
 * re-runs `fetchFn` instead of getting the poisoned failure back. */
export function fetchShared<T>(key: string, fetchFn: () => Promise<T>): Promise<T> {
  let entry = cache.get(key) as Promise<T> | undefined;
  if (!entry) {
    entry = fetchFn().catch((err) => {
      cache.delete(key); // don't poison the cache with a failed fetch — allow retry
      throw err;
    });
    cache.set(key, entry);
  }
  return entry;
}
