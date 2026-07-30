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

Audit done 2026-07-28 (two independent passes: backend — engine/strategies/
backtest/journal/DB; frontend — everything outside `chart/`, already covered
by §§1-2 and earlier sessions). Findings below, none implemented yet —
ranked by (a) live-trading risk, since these paths touch real orders, then
(b) confidence/impact. Every broker-affecting fix here still needs unit
tests + a paper-mode integration test per CLAUDE.md before it ships.

### Backend

- [x] **(High — reliability, not just speed)** Strategy-version write routes
      (`strategies/api/routes.py`: `activate_version` :114,
      `duplicate_version` :153, `rename_version` :190,
      `edit_version_code` :229 and siblings) call straight into
      `StrategyVersionService`/`versioning.py`, which is 100% synchronous
      SQLAlchemy + sandbox re-validation with **zero** `asyncio.to_thread`
      wrapping — unlike every call site in `journal/application/
      trade_journal.py`, which does wrap. This blocks the whole event loop,
      including `TradeEngine.on_candle_closed`, for the duration of any
      strategy-version write. Fix: wrap each service call in
      `asyncio.to_thread`, same pattern as the journal.
      **Done:** wrapped every write route's `StrategyVersionService` call in
      `asyncio.to_thread` (`backend/src/strategies/api/routes.py`):
      `activate_version`, `duplicate_version`, `rename_version` (calls
      `rename_family`), `edit_version_code` (calls `edit_code`),
      `update_version_spec` (calls `update_spec`), `archive_version`,
      `delete_version`, `pause_version`, `resume_version` — same
      `await asyncio.to_thread(service.method, *args, **kwargs)` idiom
      already used in `journal/application/trade_journal.py`. Each of these
      service methods (`versioning.py`) does its sandbox re-validation and
      DB write inside one synchronous method, so wrapping the single call
      keeps that whole unit off the event loop rather than splitting it.
      Read-only routes (`list_versions`, `get_version`) and the sandbox-only
      `evaluate-custom` route were left untouched — out of scope for this
      "write routes" item. Added
      `test_write_routes_run_service_calls_via_asyncio_to_thread`
      (`backend/tests/unit/strategies/test_api_routes.py`) — spies on
      `asyncio.to_thread` as seen by the routes module (still delegating to
      the real implementation) and drives all nine write endpoints through
      one version's lifecycle, asserting each route's underlying service
      method (`activate_version`, `pause_version`, `resume_version`,
      `update_spec`, `rename_family`, `duplicate_version`, `edit_code`,
      `archive_version`, `delete_version`) shows up in the recorded calls.
      `uv run ruff check src tests` and `uv run pytest` both pass (see
      report); two pre-existing, unrelated failures were confirmed present
      on `main` before this change via `git stash` (a ruff import-sort/line-
      length issue in `test_rbr_dbd_zones_scalp_xauusd_noveto.py`/
      `test_ws.py`, and a collection error in the same rbr_dbd test file for
      a missing generated strategy module) and were left alone per scope.
- [x] **(High)** `trade_loop.py:336` (`_enter_for_bot`) calls
      `AccountService.status()` (a real gateway HTTP call + keyring read)
      **once per candidate bot** inside the `for decision, strategy in
      candidates` loop (`:270-271`) — unlike candles/`symbol_info`, which
      the code already explicitly hoists to once-per-symbol (see the
      comment at `:238-243`). Balance only changes on a realized close, not
      on opening a position, so N bots on one symbol = N redundant round
      trips per candle close, every bar, on the live hot path. Fix: fetch
      once in `_try_enter` alongside `info`; re-fetch only after
      `_close_opposite_position` actually closes something.
      **Done:** hoisted the `_current_balance()` (wraps
      `AccountService.status()`) call in `_try_enter`
      (`backend/src/engine/application/trade_loop.py`) to once per
      symbol/candle-close, right alongside `info`, with a comment matching
      the existing candles/`symbol_info` hoisting comment above it.
      `_enter_for_bot` now takes `balance` as a parameter instead of
      fetching it itself, and returns the (possibly updated) balance so
      `_try_enter`'s `for decision, strategy in candidates` loop threads
      one value through every bot. `_close_opposite_position` now returns
      `tuple[list[Position], bool]` — the second element (`closed`) tells
      the caller whether it actually closed a position; `_enter_for_bot`
      re-fetches balance only when `closed` is `True`, since a realized
      close is the only thing in this loop that changes it. All existing
      `SIGNAL:`/`ENTRY BLOCKED`/`SIZING OK`/`SIGNAL FLIP` log lines are
      untouched. Added three tests to
      `backend/tests/unit/engine/test_trade_loop.py` against a new
      `FakeAccountService.calls` counter:
      `test_account_status_fetched_once_per_symbol_not_per_bot` (3
      candidate bots, 1 `status()` call), `test_account_status_
      refetched_after_close_on_opposite_signal_closes` (a flip triggers
      exactly one re-fetch, total 2 calls), and `test_account_status_
      not_refetched_when_no_close_on_opposite_signal_happens` (2 bots,
      neither closes anything, still 1 call). `uv run ruff check src
      tests` passes clean on the changed files (the two pre-existing
      failures noted in the previous checklist item — `test_ws.py` line
      length, `test_rbr_dbd_zones_scalp_xauusd_noveto.py` import sort plus
      its missing-module collection error — are untouched and unrelated).
      `uv run pytest tests/unit/engine/test_trade_loop.py`: 37 passed.
- [x] **(High)** A near-identical zone-detection routine (e.g.
      `pob_snd_zones_xauusd_v1.py:273-381`) appears in **23 generated
      strategy files** (confirmed via grep). It's a pure-Python O(n) run
      builder plus an O(runs²) merge pass over the full 200-bar context,
      recomputed **from scratch on every single `evaluate()` call** — every
      candle close, per symbol, per bot — with no per-instance memoization
      even though only the newest bar changed since the last call. This
      also means a multi-month backtest of any zone-based strategy pays
      this cost once per bar in the range, which now dominates backtest
      wall time (the runner itself is already vectorized/bit-identity
      verified — this isn't a runner regression, it's strategy-code cost
      paid N times). Fix: cache the last computed run/zone list + last
      processed bar index per strategy instance; rescan only the tail since
      the last close.
      - **Pattern designed + proven bit-identical on ONE file, 2026-07-29
        (`pob_snd_zones_xauusd_v1.py`) — NOT yet applied to the other 22.**
        Positions can't be cached directly: `evaluate()` hands the strategy
        a fixed-size *trailing* window (`get_candles`/backtest context
        builder) that slides every call — oldest bar drops, newest
        appends, and the frame gets a fresh 0-based index each time — so
        only bar timestamps are stable across calls. Design (per-instance
        `self._zone_cache`, keyed on the zone-TF bucket's absolute END
        timestamp, `zone_end_ns[i]` from `_resample`, not position `i`):
        1) On each call, diff this call's `zone_end_ns` against the
           previous call's cached array for a contiguous prefix match
           (`old_ends[p:p+L] == zone_end_ns[:L]`); no match (cold start,
           session gap) falls back to a full recompute and reseeds the
           cache from it.
        2) Cache the **pre-merge** (raw) runs, never the post-merge
           result. The weak-run merge (`is_leg(d1) and is_leg(d2)` gate) is
           a one-way combine with no split-back-apart path, and `is_leg`
           depends only on a run's own start/end — so a run that's still
           the *last* one in a frame can keep growing on a later call and
           flip from "too short to be its own leg" to "a leg", which
           silently invalidates an earlier merge decision if that decision
           was cached post-merge (this was caught by the walk-forward test
           below, not by inspection — it's the sharp edge to watch for
           when replicating this).
        3) Translate cached raw runs into the new frame's positions via
           `searchsorted` on `zone_end_ns`; keep only a contiguous run of
           them satisfying `atr_period <= start` (the rolling-ATR NaN-fill
           uses the first valid value, itself computed over bars including
           position 0, so nothing before `atr_period` is call-invariant)
           and `end <= overlap_len - 2` (excludes any run touching the
           *old* frame's own last position — still open/growing as of
           that call).
        4) Re-run classify+group (the O(n) part) only over the head
           (`[0, first_cached_start)`) and tail (`(last_cached_end, n)`)
           the cached prefix doesn't cover; splice head+cached+tail,
           coalesce any same-class seam, then run the weak-run merge-loop
           and leg/zone-building **fresh, in full**, over the spliced raw
           list every call (cheap — small run count, never the O(n)-bars
           part — and is what keeps merge decisions exact instead of
           baked-in-stale).
        Proof: `backend/tests/unit/strategies/test_pob_snd_zones_xauusd.py
        ::test_incremental_cache_matches_full_recompute_every_step` walks
        ~4000 bars of synthetic M5 data (regime-switching drift, weekend
        gaps) through a 200-bar sliding window one bar at a time (window
        rolls over ~19 times), comparing the incremental cache's output
        against a from-scratch `_detect_zones` recompute on the *identical*
        zone_frame at **every** step (timestamp-translated zone
        fingerprints, not just positions) — 3000+ steps checked, not just
        the end state. It caught a real bug (case above) before this note
        was written. `::test_incremental_cache_reprocesses_far_fewer_bars_
        than_full_recompute` proves the algorithmic savings claim (bars
        actually walked by the classify+group loop, steady-state
        incremental vs. cold/full) without a wall-clock benchmark. Files
        touched: `backend/src/strategies/generated/pob_snd_zones_xauusd_v1.py`
        (refactored `_detect_zones` into shared helpers + added
        `PobSndZonesXauusd._detect_zones_cached`; module-level
        `_detect_zones` itself is untouched and still used for the H1
        target-pool lookup) and the test file above. To replicate: repeat
        steps 1-4 per file, using that file's own zone-TF resample/ATR
        pipeline, and write the same two-test pair (bit-identical
        walk-forward + bars-reprocessed count) before trusting it.
        **Batch 1 done, 2026-07-29**: applied to
        `pob_snd_zones_fx_v1.py`, `pob_snd_zones_vix75_v1.py`, and
        `pob_snd_zones_vix75_v2.py` (each got its own
        `_detect_zones_cached` + a dedicated
        `test_pob_snd_zones_{fx,vix75_v1,vix75_v2}.py` test file with the
        same bit-identical-walk-forward + bars-reprocessed-count pair).
        These three have no zone-TF resample step (window = raw M5 bars)
        and track retest/break inside `_detect_zones` itself rather than
        on a separate M5 feed, so the cache key is the window's own bar
        timestamps and `_track_retest_and_break` runs fresh every call,
        uncached, same as the reference's M5 tracking.
        `pob_snd_zones_vix75_v1.py` also has its own pre-existing
        numpy-vectorized `_detect_zones` (perf note in its module
        docstring); its `_build_runs_from`/`_track_retest_and_break`
        helpers were written vectorized to match that style rather than
        copying the reference's plain Python loops. 4 of 23 files with the
        routine now done (xauusd from the original pass + these 3).
        **Batch 2 done, 2026-07-29**: applied to
        `pob_trend_confluence_xauusd_v1.py`, `pob_trend_confluence_xauusd_v2.py`,
        `trend_follow_zones_scalp_xauusd_v1.py`, and
        `trend_follow_zones_swing_xauusd_v1.py` — same `_detect_zones_cached`
        + pre-merge-raw-runs pattern, adapted to each file's own vectorized
        run-building style (matches `trend_follow_zones_*`'s existing numpy
        style rather than the reference's plain-Python loops); each got a
        dedicated test file with the same bit-identical-walk-forward +
        bars-reprocessed-count pair (48 tests total, verified independently
        by the coordinator, not just the implementing agent — see note
        below). 7 of 23 files with the routine now done; 15 remain
        (confirmed via `grep -rl leg_travel_atr_mult
        backend/src/strategies/generated/`): `rbr_dbd_zones_scalp_boom1000_v1.py`,
        `rbr_dbd_zones_scalp_btcusd_v1.py`, `rbr_dbd_zones_scalp_btcusd_v2.py`,
        `rbr_dbd_zones_scalp_m5_btcusd_v1.py`, `rbr_dbd_zones_scalp_vix75_noveto_v1.py`,
        `rbr_dbd_zones_scalp_vix75_v1.py`, `rbr_dbd_zones_scalp_xauusd_v1.py`,
        `rbr_dbd_zones_swing_boom1000_v1.py`, `rbr_dbd_zones_swing_btcusd_v1.py`,
        `rbr_dbd_zones_swing_vix75_v1.py`, `rbr_dbd_zones_swing_xauusd_v1.py`,
        `trend_structure_v3_v1.py`, `trend_structure_v4_v1.py`,
        `trend_structure_v5_v1.py`, `trend_structure_v6_v1.py`.
        **Process note, batch 2:** the implementing subagent, alongside its
        legitimate code+test changes, also created two unrelated files
        directly under `backend/src/skills/normal/xauusd/`
        (`trend_follow_zones_scalp_xauusd.yaml`,
        `trend_follow_zones_swing_xauusd.yaml`) — that directory is the
        live bot-routing table (any file there is a concurrently-active
        bot), and this was never part of the task. The coordinator caught
        this on diff audit, confirmed via `activity_logs`/`trades` that
        neither bot was ever actually routed or placed an order (checked
        before deleting), then deleted both files. The actual caching
        code/tests for this batch were independently re-verified (ruff +
        targeted tests re-run by the coordinator, not just trusted from the
        agent's self-report) and are sound. Later replication batches were
        given an explicit instruction not to create or touch anything under
        `backend/src/skills/` or `configs/`.
        **Batch 3 done, 2026-07-29**: applied to
        `rbr_dbd_zones_scalp_boom1000_v1.py`, `rbr_dbd_zones_scalp_m5_btcusd_v1.py`,
        `rbr_dbd_zones_scalp_vix75_noveto_v1.py`, and
        `rbr_dbd_zones_scalp_btcusd_v2.py` — this family's `_detect_zones` is
        byte-identical across all four (only params/symbol/POINT_VALUE and,
        for the two BTCUSD files, an unrelated additive RSI/EMA/volume TP
        confluence differ), and adds a zone-flip extension not present in
        any prior batch: an unbroken zone invalidated by a strong candle
        (body >= `flip_break_body_atr_mult` x ATR) gets a polarity-flipped
        counterpart appended, with its own independent retest/break scan.
        Followed the `pob_snd_zones_vix75_v1.py` template (no zone-TF
        resample — window is raw entry-timeframe bars — retest/break
        tracked fresh every call, not cached), split further into
        `_build_zones_from_runs` (geometry only) + a new
        `_track_zone_lifecycle` step that computes retest/break AND derives
        any flip counterpart, run fresh every call same as the reference's
        retest tracking; flip derivation reads only `broken_idx` from the
        (possibly-cache-assisted) zone list, never feeds back into the
        cached run list, so it doesn't affect cache correctness. Each file
        got the same bit-identical-walk-forward (~4200 bars, checked_steps >
        3900) + bars-reprocessed-count test pair, added to its existing test
        file; zone fingerprints include `flipped` in the comparison tuple.
        58 tests total across the 4 files (14+13+16+15), all passing; no
        regressions in the ~40 pre-existing tests across these files. 12 of
        23 files with the routine now done; remaining 11 (re-confirmed via
        `grep -rl leg_travel_atr_mult backend/src/strategies/generated/`,
        and separately checked `trend_structure_v7_v1.py` — it does NOT
        contain `leg_travel_atr_mult` and does not need this routine):
        `rbr_dbd_zones_scalp_btcusd_v1.py`, `rbr_dbd_zones_scalp_vix75_v1.py`,
        `rbr_dbd_zones_scalp_xauusd_v1.py`, `rbr_dbd_zones_swing_boom1000_v1.py`,
        `rbr_dbd_zones_swing_btcusd_v1.py`, `rbr_dbd_zones_swing_vix75_v1.py`,
        `rbr_dbd_zones_swing_xauusd_v1.py`, `trend_structure_v3_v1.py`,
        `trend_structure_v4_v1.py`, `trend_structure_v5_v1.py`,
        `trend_structure_v6_v1.py`. No files under `backend/src/skills/` or
        `configs/` were created or touched.
        **Batch 4 done, 2026-07-29**: applied to
        `rbr_dbd_zones_scalp_vix75_v1.py`, `rbr_dbd_zones_scalp_xauusd_v1.py`,
        `rbr_dbd_zones_scalp_btcusd_v1.py`, and `trend_structure_v3_v1.py`.
        Verified first (per-file, before editing) that each file's actual
        `_detect_zones` body is byte-identical to
        `rbr_dbd_zones_scalp_xauusd_v1.py`'s (only docstrings/params/symbol/
        class name differ) — same leg-in/base/leg-out + zone-flip detector
        as batch 3, no zone-TF resample (window = raw entry-TF bars), so the
        same `pob_snd_zones_vix75_v1.py`-style cache design applies
        directly. `trend_structure_v3_v1.py` was checked specifically per
        the task's caution about the `trend_structure` family possibly being
        structurally different: its entry trigger is pure swing/structure
        (no zone concept there), but its SL anchor is looked up via its own
        `_detect_zones`, whose body is verbatim identical to the rbr_dbd
        reference (its module docstring even says so) — it fits the pattern
        for that one call site, so it was included rather than skipped.
        Split each file's `_detect_zones` into the same shared-helper set as
        the reference (`_classify_bars`, `_build_runs_from`,
        `_coalesce_adjacent_runs`, `_make_is_leg`, `_merge_weak_runs`), plus
        one `_build_zones_from_runs` per file that folds geometry, retest/
        break scanning (`_scan_retest_break`), AND the zone-flip derivation
        into a single function (batch 3 used a separate
        `_track_zone_lifecycle` step for this same logic — this batch kept
        it as one function per file instead since the flip branch reads
        `broken_idx` inline right where it's computed; behaviorally
        equivalent, just organized differently). Added a per-instance
        `_detect_zones_cached` to each of the 4 classes, keyed on the
        window's own bar timestamps (t_ns), with `evaluate()` wired to call
        it in place of the module-level `_detect_zones` (which stays
        untouched, still the stateless ground truth used by existing tests
        and the new proof tests). For `trend_structure_v3_v1.py`, note the
        cached call site sits deep inside `evaluate()` (only reached once a
        fresh swing/structure signal already passed its gates), so in
        practice it's invoked on fewer bars than a strategy that zone-checks
        every bar — this doesn't affect correctness (the cache's
        prefix-match falls back to a full recompute on any non-contiguous
        gap) but means its realized cache-hit rate in production will be
        lower than the other three files. Each file got the same two-test
        pair (bit-identical walk-forward, ~4200 bars / checked_steps > 3000,
        plus bars-reprocessed-count) appended to its existing test file
        (`test_rbr_dbd_zones_scalp_{vix75,xauusd,btcusd}.py`,
        `test_trend_structure_v3.py`); zone fingerprints include
        `retest_idx`/`broken_idx`/`flipped`. 52 tests total across the 4
        files (14+14+14+10 — trend_structure_v3 has fewer pre-existing
        evaluate()-level tests than the scalp siblings), all passing; no
        regressions in the pre-existing tests. `uv run ruff check src
        tests` clean on all touched files (the pre-existing `test_ws.py`
        line-length and `test_rbr_dbd_zones_scalp_xauusd_noveto.py`
        import-sort issues are untouched and unrelated). 16 of 23 files with
        the routine now done; remaining 7:
        `rbr_dbd_zones_swing_boom1000_v1.py`, `rbr_dbd_zones_swing_btcusd_v1.py`,
        `rbr_dbd_zones_swing_vix75_v1.py`, `rbr_dbd_zones_swing_xauusd_v1.py`,
        `trend_structure_v4_v1.py`, `trend_structure_v5_v1.py`,
        `trend_structure_v6_v1.py`. No files under `backend/src/skills/` or
        `configs/` were created or touched (confirmed via `git status
        --short` — only the 4 strategy files, their 4 test files, and this
        checklist entry changed).
        **Batch 6 done, 2026-07-29**: applied to `trend_structure_v4_v1.py`,
        `trend_structure_v5_v1.py`, and `trend_structure_v6_v1.py` (this is
        the FINAL batch of the `trend_structure`/`rbr_dbd_zones_swing_*`
        remainder — 3 of the last 7 files; the other 4
        (`rbr_dbd_zones_swing_{boom1000,btcusd,vix75,xauusd}_v1.py`) were
        assigned to a concurrent batch, see its own note for their status).
        Verified first (per-file, before editing) that each file's
        `_detect_zones` body is byte-identical to `trend_structure_v3_v1.py`'s
        (in turn identical to `rbr_dbd_zones_scalp_xauusd_v1.py`'s, batch 3/4
        lineage) — same leg-in/base/leg-out + zone-flip detector, no zone-TF
        resample (window = raw M5 bars), inline (not yet split into shared
        helpers, unlike v3 which already had this done in batch 4) — so the
        same `pob_snd_zones_vix75_v1.py`-style cache design applies directly,
        following `trend_structure_v3_v1.py`'s precedent exactly rather than
        redesigning anything. v4/v5/v6 differ from v3 only in their
        surrounding `evaluate()` logic (fixed `TP_RR=2.2` instead of v3's
        structural nearest-old-extreme TP; v5 adds an RSI(14) gate, v6 an
        EMA(20)/EMA(50) gate) — none of that touches the zone-detection call
        site itself. Split each file's `_detect_zones` into the same
        shared-helper set as the reference/v3 (`_classify_bars`,
        `_build_runs_from`, `_coalesce_adjacent_runs`, `_make_is_leg`,
        `_merge_weak_runs`, `_scan_retest_break`, `_build_zones_from_runs`
        folding geometry + retest/break + flip derivation into one function,
        matching v3's organization choice over batch 3's separate
        `_track_zone_lifecycle` step). Added a per-instance
        `_detect_zones_cached` to each of the 3 classes, keyed on the
        window's own bar timestamps (`t_ns`), with `evaluate()` wired to call
        it in place of the module-level `_detect_zones` (which stays
        untouched, still the stateless ground truth used by existing tests
        and the new proof tests). No deviations from the v3 precedent were
        needed — these three files are close enough to v3's structure
        (module-level helper functions, class `__init__`/`evaluate()` shape)
        that the replication was mechanical. Each file got the same two-test
        pair (bit-identical walk-forward, ~4200 bars / checked_steps > 3000,
        plus bars-reprocessed-count) appended to its existing test file
        (`test_trend_structure_{v4,v5,v6}.py`); zone fingerprints include
        `retest_idx`/`broken_idx`/`flipped`, same as v3's. 26 tests total
        across the 3 files (8+9+9 — v4 has one fewer pre-existing test than
        v5/v6, which each have one extra negative-gate test for their own
        RSI/EMA filter), all passing; no regressions in the pre-existing
        tests. `uv run ruff check src tests` clean on all touched files (the
        pre-existing `test_ws.py` line-length and
        `test_rbr_dbd_zones_scalp_xauusd_noveto.py` import-sort issues are
        untouched and unrelated). No files under `backend/src/skills/` or
        `configs/` were created or touched (confirmed via `git status
        --short` — only the 3 strategy files, their 3 test files, and this
        checklist entry changed). This closes out the `trend_structure`
        side of the remaining 7; see the concurrent swing-file batch's own
        note for whether all 22 replication files are now done overall.
        **Batch 5 done, 2026-07-29**: applied to the other 4 of the
        "remaining 7" — `rbr_dbd_zones_swing_boom1000_v1.py`,
        `rbr_dbd_zones_swing_xauusd_v1.py`, `rbr_dbd_zones_swing_vix75_v1.py`,
        and `rbr_dbd_zones_swing_btcusd_v1.py` (the "swing" siblings of the
        `rbr_dbd_zones_scalp_*` family done in batches 3-4). Verified first
        (per-file, before editing) that all four files' `_detect_zones`
        bodies are byte-identical to each other and to
        `rbr_dbd_zones_scalp_xauusd_v1.py`'s pre-split version (only
        docstrings/params/symbol/class name differ, confirmed via `diff` —
        no BTCUSD-specific RSI/EMA/volume confluence like the scalp BTCUSD
        variants have, that difference lives only in `evaluate()`'s TP
        pooling, not the zone detector) — same leg-in/base/leg-out + zone-
        flip detector, no zone-TF resample (window = raw M15 bars), so the
        same `rbr_dbd_zones_scalp_xauusd_v1.py`-style cache design (batch 4
        precedent) applies directly. Split each file's `_detect_zones` into
        the same shared-helper set (`_classify_bars`, `_build_runs_from`,
        `_coalesce_adjacent_runs`, `_make_is_leg`, `_merge_weak_runs`,
        `_scan_retest_break`, `_build_zones_from_runs` folding geometry +
        retest/break + flip derivation into one function, matching batch
        4's organization choice). Added a per-instance
        `_detect_zones_cached` to each of the 4 classes, keyed on the
        window's own M15 bar timestamps (`t_ns`), with `evaluate()` wired to
        call it in place of the module-level `_detect_zones` (which stays
        untouched, still the stateless ground truth used by existing tests
        and the new proof tests). No algorithmic deviations from the
        scalp-family precedent were needed — mechanical replication across
        all 4 files since their zone-detection code is identical modulo
        naming. Each file got the same two-test pair (bit-identical walk-
        forward, ~4200 M15 bars / checked_steps > 3000, plus bars-
        reprocessed-count) appended to its existing test file
        (`test_rbr_dbd_zones_swing_{boom1000,xauusd,vix75,btcusd}.py`); zone
        fingerprints include `retest_idx`/`broken_idx`/`flipped`. 44 tests
        total across the 4 files (11 each — 9 pre-existing + 2 new per
        file), all passing; no regressions in the pre-existing tests.
        `uv run ruff check src tests` clean on all touched files (the
        pre-existing `test_ws.py` line-length and
        `test_rbr_dbd_zones_scalp_xauusd_noveto.py` import-sort/collection
        issues are untouched and unrelated). No files under
        `backend/src/skills/` or `configs/` were created or touched
        (confirmed via `git status --short` — only these 4 strategy files,
        their 4 test files, and this checklist entry were touched by this
        batch). **This closes out the last of the "remaining 7" from batch
        4** — combined with batch 6's `trend_structure_v{4,5,6}_v1.py`, all
        7 files batch 4 left outstanding are now done, and all files
        identified as needing this routine (the original 23-file count,
        after `trend_structure_v7_v1.py` was confirmed in batch 4 not to
        need it) are replicated. Checking off the main bullet below.
- [x] **(Medium)** `position_manager.py:215` (`_manage`) calls
      `get_symbol_info(position.symbol)` **per open position** inside
      `on_candle_closed`'s per-position loop (`:100-106`), even though
      `_detect_bases` right above it is already correctly hoisted to
      once-per-symbol (with a comment explaining exactly this cost
      concern). Two+ open positions on the same symbol duplicate the
      gateway call. Fix: fetch `info` once in `on_candle_closed`, pass into
      `_manage`.
      **Done:** `on_candle_closed` (`position_manager.py:100-111`) now fetches
      `info = await self._market_data.get_symbol_info(symbol)` once, right
      after the existing `_detect_bases(symbol)` hoist and inside the same
      `if positions:` guard, with a comment pointing at that same
      once-per-symbol pattern. `_manage` no longer calls `get_symbol_info`
      itself — its signature is now `_manage(self, position, bases, info)`,
      and the per-position loop passes the single fetched `info` to every
      position on that symbol. No decision logic, log statements, or
      behavior changed for the 0/1-position case. Test: added
      `test_get_symbol_info_fetched_once_per_symbol_with_multiple_positions`
      (`test_position_manager.py`) — two open positions on the same symbol,
      asserts `FakeMarketData.symbol_info_calls == ["XAUUSD"]` (a new call
      counter added to the fake) while both positions still get managed off
      that one fetch. Full `tests/unit/engine/test_position_manager.py` (17
      cases) and `ruff check src tests` both clean.
- [x] **(Medium)** `trade_journal.py:156,160` (`get_symbol_analytics`,
      `get_bot_analytics`) each independently call `repository.get_all()`
      (`repository.py:85-92`) — an unbounded `SELECT *` over the whole
      `trades` table, deserializing four JSON snapshot columns
      (`m5/h1_entry/exit_snapshot`, `structure`) that `analytics.py` never
      reads. A dashboard load hitting both endpoints does two full-table
      scans with no caching or shared fetch; cost grows unboundedly since
      `trades` (unlike `activity_logs`) is never purged. Fix: share one
      `get_all()` fetch between the two, and add a slim analytics-only
      query excluding the JSON columns.
      **Done:** shared-fetch part doesn't apply — verified via
      `journal/api/routes.py:261,279`: `get_symbol_analytics`/`get_bot_analytics`
      back two independent REST endpoints (`GET .../analytics/symbols` and
      `GET .../analytics/bots`), and `frontend/.../useAnalytics.ts:27` calls
      them as two separate HTTP requests (`Promise.all`), not one shared
      backend call — there is no single request path to hoist a fetch
      across. The slim-query part (the change that matters regardless) is
      done: added `JournalRepository.get_all_for_analytics`
      (`repository.py`) which `select()`s only `id, symbol, volume,
      open_time, close_time, profit, skill, strategy_version` — the exact
      fields `domain/analytics.py`'s aggregation reads — instead of the full
      ORM row, so SQLAlchemy never touches the four JSON columns. Added a
      slim projection dataclass `TradeAnalyticsRecord` (`domain/models.py`)
      and widened `compute_symbol_analytics`/`compute_bot_analytics`
      (`domain/analytics.py`) to accept `AnalyticsRecord = Union[TradeRecord,
      TradeAnalyticsRecord]` (structural — both types expose the same
      attributes the aggregation touches). `trade_journal.py`'s two methods
      now call `get_all_for_analytics` instead of `get_all`. Output values
      are unchanged — this only shrinks what's fetched/deserialized. Tests:
      `test_compute_symbol_analytics_bit_identical_for_slim_records`,
      `test_compute_bot_analytics_bit_identical_for_slim_records`,
      `test_trade_analytics_record_has_no_json_snapshot_or_structure_fields`
      (`test_analytics.py`); `test_get_all_for_analytics_matches_get_all_core_fields`,
      `test_get_all_for_analytics_omits_json_snapshot_and_structure_fields`,
      `test_get_all_for_analytics_scopes_to_account` (`test_repository.py`);
      `test_analytics_methods_use_slim_query_not_full_get_all`
      (`test_trade_journal.py`, asserts `get_all` is called 0 times and
      `get_all_for_analytics` 2 times across both service methods). Full
      `tests/unit/journal/` (60 cases), `ruff check src tests`, and the full
      `uv run pytest` suite all clean.
- [x] **(Medium)** `trades` (migrations `2e2c7d5ffc02`, `885996aa6537`) only
      has single-column indexes on `symbol` and `account_id`. Every hot
      query (`get_last_n`, `get_markers`, `get_open`, `count_closed`,
      `search`) filters both together, so SQLite can use only one index and
      row-filters the rest. Fine today (366 rows); degrades as trades
      accumulate. Fix: add
      `Index("ix_trades_account_symbol_close", "account_id", "symbol", "close_time")`.
      **Done:** added the composite index to `TradeRow.__table_args__` in
      `backend/src/journal/adapters/orm.py`, and a new Alembic migration
      `8dcb0a322997` (`backend/migrations/versions/8dcb0a322997_add_composite_account_symbol_close_.py`,
      chained onto head `42463adaeda9`) that runs
      `op.create_index('ix_trades_account_symbol_close', 'trades', ['account_id', 'symbol', 'close_time'])`
      in `upgrade()` and drops it in `downgrade()`. Verified upgrade/downgrade
      apply cleanly through the full migration chain against a scratch SQLite
      DB (`TB_DATABASE_URL` override), confirming column order via
      `PRAGMA index_info`. New tests in `tests/unit/journal/test_repository.py`:
      `test_trade_row_declares_composite_account_symbol_close_index` (ORM
      declaration + column order) and `test_composite_index_is_created_in_sqlite`
      (the index actually materializes via `Base.metadata.create_all`). Full
      `uv run ruff check src tests` clean (no new errors — pre-existing
      unrelated errors only in `src/journal/domain/analytics.py`,
      `tests/unit/market_data/test_ws.py`,
      `tests/unit/strategies/test_rbr_dbd_zones_scalp_xauusd_noveto.py`), and
      the full `uv run pytest` suite: 1307 passed in 998.51s.
- [x] Confirmed good, no action needed: `candles`' composite PK
      `(account_id, symbol, timeframe, time)` already matches every
      hot-path filter shape (equality on the first three, range on `time`),
      so it already serves `get_latest`/`get_before`/`get_range` as an
      efficient covering B-tree prefix — no separate index needed.

### Frontend (outside `chart/`, already covered by §§1-2)

- [x] **(Medium-High)** `app/page.tsx:157,162` calls both `useTrading(symbol)`
      and `useAllPositions()` unconditionally — each independently
      `setInterval`s every 3s (`useTrading.ts:49-58,60-64`;
      `useAllPositions.ts:40-58`) hitting `getPositions`/`getPendingOrders`.
      The symbol-filtered result `useTrading` polls is always a subset of
      what `useAllPositions` already fetched, on its own separate 3s timer,
      on the same page — 2 redundant REST round-trips every 3s, forever, on
      the busiest route in the app. Fix: derive `useTrading`'s
      `positions`/`pendingOrders` by filtering `useAllPositions`'s result by
      `symbol` (`useMemo` at the call site) instead of polling twice.

      **Done:** Changed `useTrading`'s signature to
      `useTrading(symbol, allPositions: AllPositions)` (option (a) from the
      finding) rather than filtering in `page.tsx` — every other multi-arg
      hook in `features/chart/` (`useChartEngine`, `useIndicators`,
      `useDrawingTools`, `useOrderPopovers`, …) takes its dependencies as
      constructor params rather than the call site pre-deriving state, so
      this keeps `useTrading` consistent with that composition style and
      avoids prop-drilling `allPositions` through `page.tsx`'s JSX.
      `useTrading.ts` no longer owns any position/pending-order state or
      polling: `positions`/`pendingOrders` are now `useMemo`-filtered slices
      of `allPositions.positions`/`allPositions.pendingOrders` by `symbol`
      (same `PositionOut[]`/`PendingOrderOut[]` shape, so nothing downstream
      — `TradePanel`, `MultiChartLayout` — needed to change), and all six
      mutate actions (`openMarket`, `placePending`, `close`,
      `modifyPositionSlTp`, `modifyPending`, `cancelPending`) now call
      `allPositions.refresh()` instead of a private `refresh()`/poll. Removed
      the `getPositions`/`getPendingOrders`/`setInterval`/`POLL_MS` bits from
      `useTrading.ts`; `useAllPositions.ts` untouched, still owns the single
      3s poll. `placementMode`/`draftOrder`/`placeFromClick` UI state
      unchanged. `page.tsx` now calls `useAllPositions()` once and passes it
      into `useTrading(symbol ?? "", allPositions)`. Files: `useTrading.ts`,
      `app/page.tsx`. `pnpm lint` and `pnpm build` both pass clean (verified
      2026-07-29).
- [x] **(Medium)** No request-level caching/dedup layer:
      `shared/api/client.ts:61-95` is a bare `fetch` wrapper — no cache, no
      in-flight dedup, no SWR/TanStack Query. Every hook manages its own
      loading/poll state from scratch, which is what lets the finding above
      exist and blocks fixing that class of bug generally (e.g.
      `useAllPositions` is also called independently from
      `BotsBySymbolPanel.tsx:69` on another route). Fix: adopt SWR or
      TanStack Query as the fetch layer, or at minimum a small keyed
      in-flight/response cache in `client.ts`.

      **Done:** Adopted TanStack Query (`@tanstack/react-query@5.101.4`) —
      not the smaller in-flight-cache alternative — per explicit user
      decision between the two options. Scoped to `features/trading/` only
      in this pass, the highest-value/best-understood case since
      `useTrading`/`useAllPositions` were just reworked above; migrating
      `features/chart/`, `features/strategies/`, `features/analytics/` is a
      separate, already-tracked follow-up, deliberately out of scope here.
      Added `shared/api/query-client.tsx` (`QueryProvider`, mounted in
      `app/layout.tsx` around the tree the same way `AccountProvider`
      already is) and `shared/api/queryKeys.ts` (the
      `queryKeys.<feature>.<resource>(accountId, ...)` convention, documented
      in-file, meant to extend to the deferred features). `useAllPositions`
      now runs three `useQuery`s (positions, pendingOrders, openTrades) with
      `refetchInterval: 3000` reproducing the prior 3s poll, and
      `needsTradeHistory` gates the openTrades query via `enabled` instead of
      an early-return; `refresh()` calls `queryClient.invalidateQueries` on
      the account-scoped keys. `useTrading`'s six mutate actions
      (`openMarket`, `placePending`, `close`, `modifyPositionSlTp`,
      `modifyPending`, `cancelPending`) now wrap `useMutation`s whose
      `onSuccess` calls `allPositions.refresh()` — same invalidation,
      triggered on mutation success instead of after a manual `await`. Both
      hooks keep their exact returned shape, so every consumer
      (`BotsBySymbolPanel.tsx`, `AllOrdersPanel.tsx`, `OrdersDock.tsx`,
      `app/page.tsx`) needed zero changes. Files:
      `shared/api/query-client.tsx` (new), `shared/api/queryKeys.ts` (new),
      `useAllPositions.ts`, `useTrading.ts`, `app/layout.tsx`,
      `package.json`, `pnpm-lock.yaml`. `pnpm lint` and `pnpm build` both
      pass clean (verified 2026-07-29).

      **Follow-up (2026-07-29):** Extended the same migration to
      `features/strategies/` and `features/analytics/`, per the
      already-tracked plan above. Added `strategies` (`versions`,
      `activeVersions`, `skillAssignments`, `botCounts`) and `analytics`
      (`symbols`, `bots`) namespaces to `queryKeys.ts`, same shape as
      `trading`. `useActiveStrategyForSymbol.ts` now runs one `useQuery`
      (`refetchInterval: 5000`, same cadence as before), with the
      reference-stable "same strategy version" derivation kept as a small
      `useEffect`/`useState` on top so polling an unchanged version still
      doesn't hand consumers a new object reference. `BotSelector.tsx`
      (a surgical conversion only — its other pre-existing uncommitted
      changes were left untouched) now runs three `useQuery`s: `versions` +
      `skillAssignments` (`refetchInterval: 5000`, `refetchOnWindowFocus:
      true` replacing the old manual focus/visibilitychange listeners) and
      `botCounts` (`refetchInterval: 15000`, keyed on the sorted active-bot-
      name list so the per-bot fan-out doesn't re-fire on every assignments
      poll tick). `useAnalytics.ts` had no polling (one-shot fetch on mount)
      but was migrated anyway for the caching/dedup/loading/error-state
      benefits and to keep one fetch layer app-wide; two one-shot
      `useQuery`s (`symbols`, `bots`), `refresh()` now invalidates both
      query keys instead of re-running a manual fetch. All three hooks and
      `BotSelector.tsx` keep their exact returned shape/props, so every
      consumer (`AnalyticsPage.tsx`, `app/page.tsx`) needed zero changes.
      `features/chart/` remains the sole deferred folder (separate, more
      careful pass planned due to unrelated in-progress work there). Files:
      `shared/api/queryKeys.ts`, `features/strategies/BotSelector.tsx`,
      `features/strategies/useActiveStrategyForSymbol.ts`,
      `features/analytics/useAnalytics.ts`. `pnpm lint` and `pnpm build`
      both pass clean (verified 2026-07-29).

      **Follow-up (2026-07-30): attempted, then reverted.** `features/chart/`
      was the one deferred folder — flagged higher-risk going in because
      `sharedPoll.ts` (a hand-rolled ref-counted poller, same "N mounted
      windows share one fetch loop" pattern `shared/api/ws.ts` uses for room
      subscriptions) is load-bearing infra for the multi-window chart layout
      (up to 4 `ChartPanel` instances open on one symbol). All 4
      `subscribeSharedPoll` call sites (`useCandleData.ts` symbol-info poll +
      news-window poll, `useBacktestData.ts` live-bot markers poll,
      `ChartPanel.tsx` trade-markers poll) were converted to `useQuery`, with
      careful per-call-site reasoning for error/late-subscriber parity (see
      git history for the attempt's full diff if useful as reference) — lint
      and build both passed clean.

      **Live browser verification (opening two `ChartPanel` windows on the
      same symbol, watching DevTools Network) then caught a real regression
      the semantic reasoning missed**: TanStack Query's `refetchInterval` is
      scheduled *per observer* (per mounted `useQuery` call), not once per
      shared cache entry — query-key-based caching dedupes the *data*, but
      each mounted component still independently drives its own interval
      timer, so N windows on one symbol produced ~N× the requests
      `sharedPoll.ts` used to send (measured: 4-8 requests in ~4s against a
      3000ms poll interval, vs. sharedPoll's genuine one-timer-per-key
      guarantee). This is the opposite of the checklist item's goal, so the
      whole `features/chart/` change was reverted: `sharedPoll.ts` restored
      byte-for-byte, all 4 call sites reverted to `subscribeSharedPoll`, the
      `chart` namespace removed from `queryKeys.ts`. Confirmed via
      `git diff --stat` that `sharedPoll.ts` shows zero diff against the
      committed baseline post-revert, and `pnpm lint`/`pnpm build` both pass
      clean on the reverted state. `features/chart/` keeps `sharedPoll.ts`
      until a version of this migration exists that reproduces true
      single-timer sharing (e.g. one singleton poller per query key driving
      `queryClient.invalidateQueries`, with individual `useQuery` calls set
      to `refetchInterval: false`) — not attempted in this pass.
      `features/trading/`, `features/strategies/`, and `features/analytics/`
      remain migrated and unaffected by this revert.

      **Separate finding surfaced during this verification, NOT caused by
      today's work, left unfixed (out of scope for this pass) — flagged for
      a future session:** even on the *reverted*, original `sharedPoll.ts`
      code, on a freshly-restarted dev server, with only ONE `ChartPanel`
      window open (no multi-window factor at all), the symbol-info poll
      fired 5-8 requests in ~4 seconds against its stated 3000ms interval —
      confirmed via `grep -rn "getSymbolInfo("` that there is only one call
      site in the whole frontend, so this isn't a multiple-independent-
      callers issue either. This means something is repeatedly tearing down
      and rebuilding `useCandleData`'s poll effect (each rebuild re-triggers
      `subscribeSharedPoll`'s "immediate fetch for a new poller entry"
      behavior) far more often than intended, independent of the TanStack
      question entirely — a pre-existing characteristic of the current
      uncommitted chart code, not something this pass introduced or fixed.
      Worth investigating: effect-churn from an unstable dependency, or
      excessive re-mounting of the chart tree, is a real cost on a
      live-trading data endpoint regardless of which polling mechanism sits
      underneath it.
- [x] **(Medium)** `ChartPanel.tsx` statically imported
      `BacktestStrategyEditor`, which statically imports
      `@uiw/react-codemirror` + `@codemirror/lang-python` +
      `@uiw/codemirror-theme-github` (`BacktestStrategyEditor.tsx:11-13`).
      It only renders when `showStrategyEditor` is true, but the static
      import shipped the full editor + Python language mode in the main
      `/` route's bundle for every visit regardless of whether the toggle
      is ever used. Fix: `next/dynamic(() => import(".../BacktestStrategyEditor"),
      { ssr: false })`.

      **Done:** the `BacktestStrategyEditor` dynamic-import conversion above
      was a first pass that turned out to be incomplete — `ChartPanel.tsx`
      had a **second**, independent user of the same three packages: a raw
      inline `<CodeMirror>` "Run Custom Code" drawer (`showCustomCodeEditor`,
      distinct from `BacktestStrategyEditor`'s own `showStrategyEditor`
      toggle), with its own top-level `import { python } from
      '@codemirror/lang-python'`, `githubDarkInit` theme, and `CodeMirror`
      import directly in `ChartPanel.tsx`. Since those were static top-level
      imports in `ChartPanel.tsx` itself, they kept shipping in the main
      bundle no matter what the first pass did to `BacktestStrategyEditor`.
      This pass extracted that whole drawer block into a new
      `features/chart/CustomCodeDrawer.tsx` (`CustomCodeDrawerProps`,
      `memo`-wrapped, owns its own `cmTheme`/`python()`/`CodeMirror` imports
      — mirrors the `BacktestStrategyEditor.tsx` precedent) and swapped
      `ChartPanel.tsx`'s inline JSX for
      `next/dynamic(() => import('./CustomCodeDrawer').then(m => m.CustomCodeDrawer), { ssr: false })`,
      passing through `drawerPosition`/`customCodeDraft`/`customCodeBusy`/
      `customCodeError`/`customCodeResult`/`customCodeCopied`/
      `handleCopyCustomCode`/`runCustomCode`/`clearCustomCode`/`setDrawerPosition`/
      `setCustomCodeDraft`/`onClose`. `ChartPanel.tsx` no longer has any of
      the three package imports or the `cmTheme` constant. Behavior
      (positioning, handlers, conditional render) is unchanged.

      **Verification (real, not assumed):** built with `pnpm build` and
      inspected `.next/server/app/index.html`'s `<script src>` tags plus
      the `/page` entry in `page_client-reference-manifest.js`. Confirmed
      the actual `CustomCodeDrawer` component chunk (the one containing its
      "Run Custom Code" JSX, 3.9 KB) and the actual `BacktestStrategyEditor`
      component chunk (containing `editStrategyVersionCode` etc.) are
      **not** in the `/` route's entry chunk list — both only exist in
      chunks fetched on demand when their `dynamic()` import resolves.
      Isolated the effect of *this* pass specifically (reverted just the
      `CustomCodeDrawer` split, rebuilt, diffed): total entry-chunk bytes
      for `/` dropped from 1,895,710 → 1,892,741 (removes the drawer's own
      ~3 KB, source-level split is real and correct).

      **Important caveat found during verification — goal not fully met
      end-to-end:** ~960 KB of `@codemirror`/`@uiw` bytes (chunk
      `3ltkj3vjffbh7.js`, 471 KB, containing raw `@codemirror/state`
      `EditorView` internals; plus two inlined `githubDarkInit(...)` theme
      calls inside `ChartPanel.tsx`'s own compiled chunk) still ship in
      `/`'s initial `<script>` tags. Root cause is **not** in
      `ChartPanel.tsx`/`CustomCodeDrawer.tsx`: `/backtest/[id]`
      (`BacktestReportDetail.tsx`) renders `<BacktestStrategyEditor>`
      unconditionally (no toggle — it's always visible on that page), and
      Next/Turbopack's automatic chunk-splitting hoists the shared
      `@codemirror`/`@uiw` dependency graph into a chunk referenced by
      **both** routes' entry manifests, even though `/` only reaches it via
      `dynamic()`. Confirmed this is pre-existing and unrelated to this
      pass: reverted to the prior-pass-only state (`BacktestStrategyEditor`
      dynamic, `CustomCodeDrawer` still inline) and rebuilt — the exact same
      471 KB chunk (byte-identical hash) was already present in `/`'s entry
      list before this pass touched anything. Fixing this fully would mean
      changing `/backtest/[id]`'s always-on usage (out of scope here, and a
      dynamic import there buys nothing since it's never conditionally
      rendered) or accepting this as a Next.js/Turbopack shared-chunk
      limitation. Filed as a follow-up, not silently claimed as solved.
- [x] **(Low)** `useAllPositions.ts:46-51` fetches trade history
      (`getTradeHistory(..., limit: 500)`) every 3s from `page.tsx` even
      when `OrdersDock`'s panel is hidden (`OrdersDock.tsx:67` only gates
      rendering, not the fetch). Fix: gate that leg of `refresh()` behind a
      "panel visible" flag, or lower its cadence independently.

      **Done:** `useAllPositions(options?: { needsTradeHistory?: boolean })`
      now takes an optional flag, default `true`, that gates only the
      `getTradeHistory` leg of `refresh()` — `getPositions`/`getPendingOrders`
      still run unconditionally since they feed the header P/L regardless of
      dock visibility. Chose a notify-only callback over full prop-lifting:
      `OrdersDock` keeps owning/persisting its own `visible` state exactly as
      before (still reads `tb.ordersDock.visible` from `localStorage`
      post-mount), but now also calls a new optional `onVisibleChange` prop
      whenever `visible` changes (including the initial post-mount read).
      `page.tsx` keeps a local `ordersDockVisible` state (default `true`,
      matching `OrdersDock`'s own pre-mount default) fed by that callback and
      passes `useAllPositions({ needsTradeHistory: ordersDockVisible })`.
      This mirrors the existing hook-reads-its-own-toggle style used
      elsewhere (`useChartUIToggles.ts` reads its localStorage keys directly
      rather than being handed lifted state) while avoiding the drift risk of
      having two independent readers of the same key with no change
      notification between them. When gated off, `skillByTicket`/
      `openTradeByTicket` are deliberately left at their last-known values
      (not cleared) — the next 3s poll after re-showing the dock refetches
      naturally, and brief staleness reads better than a "no data" flash;
      confirmed by checking `AllOrdersPanel.tsx`, which renders whatever the
      map currently holds with no separate loading/empty state to fight with.
      No forced immediate refetch on toggle-back-on — the existing 3s
      interval covers it, so no behavior change beyond skipping the fetch
      while hidden. `BotsBySymbolPanel.tsx` (via `bot-control/page.tsx`)
      calls `useAllPositions()` with no arguments, so it defaults to `true`
      and its trade-history fetch is completely unaffected — confirmed via
      `git diff --stat`, neither `bot-control/page.tsx` nor
      `BotsBySymbolPanel.tsx` were touched. Files: `useAllPositions.ts`,
      `OrdersDock.tsx`, `app/page.tsx`. `pnpm lint` and `pnpm build` both
      pass clean (verified 2026-07-29).
- [x] **(Low)** `BotsBySymbolPanel.tsx:38-49` (`closeBotAndPositions`)
      `await`s `closePosition` one ticket at a time in a `for` loop instead
      of `Promise.allSettled`, serializing N broker round-trips when a bot
      holds several positions. Fix: `Promise.allSettled`, then aggregate
      per-ticket errors same as today.

      **Done:** `closeBotAndPositions` now fires all `closePosition(accountId,
      ticket)` calls concurrently via `Promise.allSettled`, then iterates the
      settled results in original ticket order — identical per-ticket error
      message format (`ApiError` message or generic "failed to close",
      surfaced via the same `onError` callback → `errors` toast list) and the
      same "left active — not every position closed" summary when any ticket
      fails. `removeBotFromSymbol` still only runs after the whole batch
      settles, unchanged. No pre-existing test coverage for this component or
      any other in `frontend/src` (no `.test.tsx`/`.test.ts` files anywhere in
      the frontend), so none was added — noting for the coordinator to decide.
      `pnpm lint` and `pnpm build` both pass.
