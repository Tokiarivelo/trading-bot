# Bot session replay + rejected-signal reasons — implementation plan

Scope: the dock opened by the eye icon on a bot in the bot list
(`SignalsDock`, tabs Signals / Trades / Indicators, mounted from
`ChartPanel.tsx` when `liveBotSkill` is set).

## Status

- Phase 1 — backend signal `price` + rejection-reason coverage: done
  (implemented twice; first pass was wiped by an outside commit).
- Phase 2 — "Replay" tab in the bot dock: done (also re-done after the wipe).
- Phase 3 — blinking reveal markers during play: done.
- Phase 4 — rejected-signal reason tooltip: done.
- Phase 5 — verification: lint + build green; not yet verified in a browser.

## What already existed (was reused, not rebuilt)

- `useReplayEngine.ts` — cursor, autoplay tick, speed, `handleStartSessionReplay`
  (arbitrary period, chunked fetch), `handleEnterReplay`/`handleExitReplay`,
  `seekTo`, `navigateToTime`; `ReplayControls.tsx` + `SessionReplayPicker.tsx`.
- `useBacktestData.ts` — the live-bot eye poll feeds `getLiveBotSignals` +
  `getTradeMarkers` into the same `backtestSignals`/`backtestTrades` state a
  backtest report uses; the marker-application effect already gates markers by
  `cursorTime` while `replayActive` ("no lookahead").
- `GET /accounts/{id}/activity/signals` already returned `time`, `direction`,
  `outcome`, `reason` per signal.
- `ZoneInfoPopover.tsx` + ChartPanel's zone click hit-test = the pattern for a
  click-to-inspect tooltip anchored in the chart container.

## Phase 1 — Backend: signal price + reason coverage

- `price: float | None` on `BotSignal` (`activity/domain/models.py`) and
  `BotSignalOut` (`activity/api/schemas.py`, with a `Field` description), passed
  through in `activity/api/routes.py`.
- Engine veto/reject log lines (`engine/application/trade_loop.py`) fixed so
  every rejection path emits a skill token and a human-readable reason the
  parser captures.
- **Bug found:** commit `bdab6e1` added a `(N target position(s))` segment to
  the `SIGNAL:` log line, breaking `_SIGNAL_RE` in
  `activity/application/bot_signals.py` *and* `backtest/application/signals.py`
  — live signal trails and backtest report signals had been returning nothing
  since. Both regexes now tolerate the current and legacy formats.
- Outcome vocabulary must stay within the existing values: the frontend indexes
  `SIGNAL_OUTCOME_META[outcome]` unguarded and an unknown value crashes the chart.

## Phase 2 — Frontend: "Replay" tab in the bot dock

- 4th tab in `SignalsDock.tsx`, live-bot eye only (not backtest reports), body in
  memoized `BotSessionReplayTab.tsx`.
- Session bounds derived from the bot's own signals+trades (first→last, 1h pad,
  clamped to now; last 24h when empty), editable From/To, speed select, Play.
- Drives the existing engine via a new `startSessionReplayForRange(from, to)` in
  `useReplayEngine.ts`; controls typed as `BotReplayControls` in `types.ts` and
  threaded from `ChartPanel.tsx` so the dock stays presentational.
- No new polling — reuses `backtestSignals`/`backtestTrades`.

## Phase 3 — Blinking reveal markers during play

- `useReplayReveal.ts` emits transient reveal events as the cursor crosses a
  trade's `open_time`/`close_time` or a rejected signal's time; events expire
  after ~2.5s, max 6 concurrent, cleared on backward seek / replay exit.
- `ReplayRevealOverlay.tsx` renders "BUY HERE" / "SELL HERE" / exit labels,
  positioned via `timeToCoordinate`/`priceToCoordinate`, blinking via
  `animate-pulse`, `@theme` tokens only. Inert when replay is off.

## Phase 4 — Rejected-signal reason tooltip

- `SignalInfoPopover.tsx` (modelled on `ZoneInfoPopover.tsx`) shows direction,
  outcome badge (`SIGNAL_OUTCOME_META`), timestamp, optional price and the full
  `reason` on clicking a non-`opened` square marker.
- Hit test: nearest candle to `param.time`, non-`opened` signals at that bar,
  click y within a band below the low (buy) / above the high (sell); drawings
  keep priority so the zone popover wins. Works during replay and in the normal
  eye view.

## Phase 5 — Verification

- `make lint-frontend` and `make build-frontend` green; backend `ruff` + `pytest`
  (known pre-existing failures: two deleted strategy modules break collection,
  and `test_risk_config_has_user_owned_caps` fails on the user-owned
  `configs/risk.yaml`).
- Still to do: manual check in the running app on port 3001 with the eye on a
  bot that has rejected signals.
