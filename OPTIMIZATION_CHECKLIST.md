# Optimization & Candle-Gap Fix — Implementation Checklist

Scope: (1) the candle-history gap after a long service downtime, root-caused
against the current uncommitted diff on `main`; (2) market-data pipeline
efficiency findings from that same review; (3) an app-wide optimization pass
(backend engine/strategies/backtest/journal/DB, frontend beyond the chart).
Findings 1–2 are from a full trace of the actual code paths (file:line cited).
Section 3 to be filled in from the broader app-wide audit.

---

## 1. Candle-history gap after long downtime — root cause & fix

**Root cause:** `CandleStreamService.poll_once` (`backend/src/market_data/application/candle_stream.py:38,152`)
fetches only the last `_POLL_LOOKBACK = 20` bars per symbol/timeframe on
every poll. On restart after a long outage, only those 20 fresh bars get
upserted — everything between the last bar stored before shutdown and
`now − 20 bars` is never fetched. `CandleHistoryService.backfill()`
(`backend/src/market_data/application/history.py:64-99`), which could fill
exactly this hole, is only ever invoked manually via
`POST /market-data/backfill` (`backend/src/market_data/api/routes.py:142-179`).
`backend/src/main.py`'s `lifespan` calls `candle_stream.start()` directly
with no gap-reconciliation step first.

**Made worse by the in-progress uncommitted diff:** the new DB-first read
path in `get_candles` (`history.py:42-55`) treats the DB as fresh as soon as
`cached[-1].time == timeframe.last_closed_open(now)` — which the restart's
20-bar poll satisfies within ~1s — so it now serves straight from the
gap-blind `CandleRepository.get_latest`/`get_before` (plain
`ORDER BY time DESC LIMIT`, no continuity check, `candle_repository.py:67-96`)
and **never calls the gateway again** to notice the hole. Pre-diff, the
gateway was hit first on every chart load, so a healthy-gateway restart got
a continuous read and the gap stayed latent in the DB only.

Also: an open chart tab does not refresh history on WS reconnect — it only
restores room membership (`backend/src/market_data/api/ws.py:120-149`,
`frontend/src/shared/api/ws.ts:39-43`) and keeps stale in-memory bars,
receiving only incremental `candle_closed`/`candle_update` deltas going
forward (`ChartPanel.tsx:3470-3513`).

- [x] Add automatic gap reconciliation at startup, before
      `candle_stream.start()` in `backend/src/main.py`'s `lifespan`: for each
      configured symbol/timeframe, compare the DB's last stored bar time to
      `now`; if the gap exceeds `_POLL_LOOKBACK × timeframe.seconds`, call
      `candle_history.backfill(symbol, timeframe, count, start=last_stored_time)`
      to page exactly the missing window before streaming begins.
      **Done:** added `CandleHistoryService.reconcile_gaps()`
      (`backend/src/market_data/application/history.py`), called from
      `lifespan` (`backend/src/main.py`) before `candle_stream.start()`.
      Renamed `candle_stream._POLL_LOOKBACK` to public `POLL_LOOKBACK` so
      both sides share one constant. Per symbol/timeframe: skips symbols with
      no stored history yet (cold-open path handles those), skips gaps
      within `POLL_LOOKBACK` bars, and swallows `MarketDataUnavailable` per
      pair so a down gateway at startup doesn't block the rest or delay
      startup. Unit tests in `backend/tests/unit/market_data/test_history.py`
      (`test_reconcile_gaps_*`, 4 new cases). Manual verification (stop/
      restart past the lookback window) still outstanding — see the last
      bullet in this section.
- [x] Add a continuity check to `CandleHistoryService.get_candles`'s DB-first
      fast path (`history.py:44-55`), e.g. verify
      `cached[-1].time - cached[0].time == (len(cached) - 1) * timeframe.seconds`
      (accounting for weekend/session closures), and fall through to the
      gateway (or trigger a targeted backfill) when it fails instead of
      trusting `get_latest`/`get_before` blindly. Apply the same check to the
      `before`-set paging branch (`history.py:50-55`), which has identical
      exposure.
      **Done:** added `_has_internal_gap()` (`history.py`) — flags any
      consecutive-bar gap in the cached window wider than a 3-day
      weekend/holiday allowance (`_MAX_SESSION_GAP`), skipped for W1/MN whose
      spacing already spans calendar gaps by design. Both the `before is
      None` and `before`-set branches now require `not
      _has_internal_gap(cached, timeframe)` alongside their existing
      freshness/completeness checks before returning the DB copy early;
      a detected gap falls through to the gateway fetch, same as a stale or
      short cache.
- [x] Add a unit test with a **gapped** `FakeCandleRepository` fixture (the
      diff's existing tests in `backend/tests/unit/market_data/test_history.py`
      only use contiguous fixtures — none exercise this exact regression).
      **Done:** `test_get_candles_falls_through_to_gateway_when_db_has_internal_gap`
      and `test_get_candles_hits_gateway_when_db_page_has_internal_gap` in
      `test_history.py` — both build a bars list with a >4-day internal hole
      (fresh/full-page checks would otherwise pass) and assert the gateway
      gets hit instead of the gapped cache being served.
- [x] Have the frontend refetch/patch history on socket `connect` (not just
      re-subscribe) in `ChartPanel.tsx`, or at minimum surface a
      "reconnected — data may be stale, click to refresh" affordance.
      **Done:** added `onSocketConnect()` (`frontend/src/shared/api/ws.ts`) —
      a thin `socket.on('connect', ...)` wrapper alongside the existing
      room-resubscribe handler, so callers can hook every connect/reconnect
      without re-deriving detection themselves. `ChartPanel.tsx`'s live
      data effect registers it next to `subscribeRoom`: on each `connect`
      (guarded by `historyLoadedRef` so the initial load's own fetch isn't
      duplicated), `patchLatestHistoryOnReconnect()` refetches the latest
      `CANDLE_COUNT` bars via `getCandles` and splices them in — bars older
      than the refetched window's first timestamp are kept as-is (so
      `loadMore`-paged history survives), everything at or after it is
      replaced. Skipped for backtest/session-replay views (anchored to a
      historical window, not "now"). Un-registered in the effect's cleanup
      alongside `unsubscribe()`. `pnpm lint` passes; `pnpm build` not yet
      run (see repo-wide build step at end of this pass).
- [x] **Found live in production data, 2026-07-23:** the process never
      restarted between 2026-07-20 and 2026-07-23, so `reconcile_gaps`
      (startup-only) never ran — yet real multi-hour XAUUSD M1/M5 holes
      (~11-24h, 07-20/21/22) still opened, because the gateway/Wine terminal
      connection dropped and recovered *without* a process restart, which
      `poll_once`'s 20-bar window can't self-heal past. **Fixed:**
      `CandleStreamService.poll_once` (`candle_stream.py`) now compares the
      oldest bar in each poll's fetch to the last bar it actually emitted
      (`previous`); if that gap exceeds one bar interval (only possible once
      an outage has outlasted `POLL_LOOKBACK` bars), it calls
      `CandleHistoryService.backfill(..., start=previous)` right there,
      before emitting the tail as usual — this fires on *every* recovery
      from an outage, not just process restarts. Wired via a new optional
      `candle_history` constructor param, injected in `container.py`
      (`candle_history` now constructed before `candle_stream`). Swallows
      `MarketDataUnavailable` per pair so a still-flaky gateway just retries
      next tick. Tests: `test_poll_once_heals_gap_left_by_mid_session_outage`,
      `test_poll_once_gap_backfill_failure_does_not_crash_the_poll`
      (`test_candle_stream.py`). The actual 2026-07-20/21/22 XAUUSD M1/M5
      holes were repaired directly against the live DB via a targeted
      `CandleHistoryService.backfill(start=...)` call — verified no gaps
      remain beyond the daily ~65-70min broker rollover break (~20:55-22:05
      UTC, present throughout the whole history, not a bug).
- [ ] After the fix ships, manually verify: stop the backend for >20 bars'
      worth of the fastest configured timeframe, restart, and confirm the
      chart renders a continuous history with no hole.

---

## 2. Market-data pipeline efficiency findings

- [x] **(High)** `poll_once`'s per-symbol/timeframe loop is fully sequential
      (`candle_stream.py:147-181`, no `asyncio.gather`). At shared bar
      boundaries (e.g. top of the hour) this can be 25–45 sequential gateway
      calls in one tick; combined with the diff's new 8s read timeout
      (`mt5_gateway.py:30,79`), a degraded gateway can stretch one poll tick
      to many × 8s, delaying the *next* poll for everything — including the
      engine's own M5 entry clock. Fix: run fetches concurrently via
      `asyncio.gather` with a bounded semaphore (e.g. 5–10 in flight).
      **Done:** `poll_once` (`candle_stream.py`) now builds the list of
      symbol/timeframe pairs that actually need a fetch this tick, then
      fetches all of them concurrently via `asyncio.gather(...,
      return_exceptions=True)` behind a `_MAX_CONCURRENT_FETCHES = 8`
      semaphore; persistence, gap-backfill, and event/broadcast emission stay
      sequential afterward, in the original pair order, so ordering-sensitive
      behavior (event bus publish order, `_last_emitted` bookkeeping) is
      unchanged. `return_exceptions=True` also improves on the old strictly-
      sequential behavior: one pair hitting `MarketDataUnavailable` no longer
      aborts every other pair's already-fetched candles for the tick — the
      first such error is re-raised only after all successful pairs are
      processed, so `_run()` still flags the gateway down same as before.
      Non-`MarketDataUnavailable` exceptions still raise immediately. Note:
      this does raise the gateway's peak concurrent request load from the
      poller (up to 8 in flight vs. 1); the gateway's FastAPI routes are sync
      `def`s (Starlette threadpool) with no lock around the `MetaTrader5`
      calls in `mt5_client.py` — already true today for any two concurrent
      requests from different sources (e.g. two chart tabs), so not a new
      category of risk, but worth knowing if MT5/Wine concurrency issues show
      up under load. All 18 `test_candle_stream.py` cases pass unchanged;
      `ruff check` clean.
- [x] **(Medium)** `_POLL_LOOKBACK = 20` is one constant across all 9
      timeframes (`candle_stream.py:38`) — undersized for fast timeframes
      (the direct mechanism behind §1's gap), needlessly oversized for
      MN/W1. Scale it per timeframe, bounded by the known 200-bar engine
      hard cap.
      **Done:** replaced the flat constant with `poll_lookback_for(timeframe)`
      (`candle_stream.py`) — scales to a ~2-hour wall-clock buffer per
      timeframe (`_LOOKBACK_BUFFER_S / timeframe.seconds`), floored at 6 bars
      and capped at 200 (the engine's known `context_bars` hard cap). M1 now
      fetches 120 bars/poll (was 20 — a 20-minute buffer on a 1-minute
      timeframe), M5 24, everything H1-and-slower floors to 6 (was 20 D1
      bars = 20 days, 20 W1 = ~4.6 months, fetched pointlessly every tick).
      `poll_once` and `CandleHistoryService.reconcile_gaps` (`history.py`)
      both call it — `reconcile_gaps`'s `poll_lookback` param changed from a
      flat `int` to `Callable[[Timeframe], int]` so its startup gap
      threshold scales the same way per timeframe; `main.py` now wires
      `poll_lookback_for` straight in instead of the old `POLL_LOOKBACK`
      constant. Tests: 3 new cases for `poll_lookback_for` itself
      (fast-timeframe floor, slow-timeframe ceiling, 200-bar cap) in
      `test_candle_stream.py`; the 4 existing `reconcile_gaps` tests in
      `test_history.py` updated to pass `poll_lookback=lambda _tf: 20`. Full
      `tests/unit/market_data/` suite (92 cases) and `ruff check` both clean.
- [x] **(Medium)** `LiveCandleService.poll_one` (1.5s interval,
      `backend/src/market_data/application/live_candle.py:81`) and
      `CandleStreamService.poll_once` independently double-fetch the same
      symbol/timeframe from the gateway at every bar close for any
      actively-watched chart room. Reuse the just-fetched bar between the
      two services, or stagger intervals so they don't collide at
      boundaries.
      **Done:** added a small shared cache, `recent_candle_cache: dict[(symbol,
      timeframe) -> (time.monotonic() fetched-at, Candle)]`, constructed once
      in `container.py` and passed to both services' constructors (optional
      param, defaults to `None` so existing tests/lightweight fixtures are
      unaffected). `CandleStreamService.poll_once` writes the raw fetch's
      last element (the still-forming bar, before the closed-bars filter) to
      the cache for every pair it fetches. `LiveCandleService.poll_one`
      checks the cache first and reuses the entry if its age is within one
      `poll_interval` (1.5s) — otherwise falls through to its own gateway
      call, same as before. This targets the exact overlap described: right
      at a bar close, `CandleStreamService`'s boundary-aligned poll and
      `LiveCandleService`'s next ~1.5s tick (landing within that same window
      by construction) now share one gateway fetch instead of two. Tests:
      `test_poll_once_populates_recent_candle_cache_with_latest_bar`
      (`test_candle_stream.py`); `test_poll_one_reuses_fresh_cached_candle_
      instead_of_fetching` and `test_poll_one_ignores_stale_cached_candle`
      (`test_live_candle.py`). Full `tests/unit/market_data/` suite (95
      cases) and `ruff check` both clean.
- [x] **(Low-medium)** `loadMore()`'s pan-left pagination call in
      `ChartPanel.tsx:3291-3296` doesn't thread an `AbortSignal`, unlike the
      initial-history and session-replay fetches the diff already updated
      (`ChartPanel.tsx:3357-3388`). A symbol/timeframe switch mid-pan lets
      that request run to completion server-side even though the client
      discards the result. Thread a signal through it too.
      **Done:** `loadMore()`'s `getCandles` call now passes
      `initialLoadController.signal` (the same per-effect-run controller
      already used for the initial-history and session-replay fetches, and
      already aborted in this effect's cleanup on symbol/timeframe/report
      change or unmount) as its 5th argument. The existing generic
      `catch { /* leave hasMore true, next pan retries */ }` already handles
      an aborted fetch the same as any other transient failure, and the
      `finally` block already guards its state resets on `!cancelled`, so no
      further changes were needed there. `pnpm lint` clean.
- [ ] **(Low)** The new DB-first path in `get_candles` (`history.py:42-55`)
      adds one extra DB round trip before falling through to the gateway on
      a genuinely cold open (symbol/timeframe never streamed) — small but
      real added latency vs. the pre-diff single-gateway-call path. Note
      only; not worth a structural fix on its own, likely subsumed by the
      continuity-check fix in §1.
- [x] Confirmed good, no action needed: the `fetchCandlesForPeriod` fix in
      the diff (`ChartPanel.tsx:265-296`) replacing per-page
      `acc = [...batch, ...acc]` (O(n²) over a period spanning many chunks)
      with a single `pages.reverse().flat()` at the end.

---

## 3. App-wide optimization pass

_Pending — broader audit beyond the chart/market-data pipeline (engine,
strategies, backtest runner, journal, risk, DB access patterns, other
frontend features) in progress._
