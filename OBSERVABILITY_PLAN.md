# Observability & Trading-Performance Plan

Goal: make the bot **debuggable** (know exactly why every signal did or didn't
become a trade), **measurable** (execution quality, not just win rate), and
**improvable** (regime-aware, cost-aware strategy research).

Derived from a read of the current code on branch `feat/bot-session-replay`
(2026-08-05). Findings that motivated it:

- `shared/logging/setup.py` is plain `logging.basicConfig` — printf messages,
  no structured logging, no metrics, no tracing.
- `activity/application/bot_signals.py` **regex-parses free-text log lines**
  back into `BotSignal`s. The decision trail is therefore coupled to log
  message wording; it has already broken twice (space-containing symbols,
  `\S+` skill parsing).
- `_OUTCOME_PREFIXES` collapses 5 distinct block reasons into `risk_rejected`,
  so "what did the volatility guard cost me" is unanswerable.
- Grep of `backend/src` for `mfe|mae|excursion|slippage|latency|retcode`
  returns **zero** hits — no execution-quality telemetry exists anywhere.
- `journal/domain/analytics.py` computes only outcome metrics (win rate, PF,
  expectancy, max DD).
- Backtests do not simulate broker `stops_level`, so M1 scalp backtests are
  fictional (see memory `broker-stops-level-not-enforced`).

## Rules for every phase

- Each phase runs in a **fresh subagent context**.
- Before-done gate, from `backend/`: `uv run ruff check src tests` and
  `uv run pytest`. Frontend phases: `make lint-frontend` and
  `make build-frontend`.
- CLAUDE.md is binding: hexagonal layering, explicit `response_model` +
  documented `Field`/`Query` on every route, no pydantic in `domain/`,
  never modify `configs/risk.yaml` limits.
- After each phase the orchestrator does a **repo-wide git diff audit**
  (including `git log --all` and `git worktree list`) — subagent
  self-reports of "I only touched X" are not trusted.
- This file is updated with the outcome before the next phase starts.

---

## Phase 1 — Typed signal decisions (replace log scraping)

**Status:** not started

Introduce a first-class decision record so the live decision trail stops being
parsed out of log text.

- New `SignalDecision` domain dataclass in `activity/domain/models.py`:
  `signal_id` (uuid), `account_id`, `bot` (skill), `strategy`, `symbol`,
  `timeframe`, `direction`, `price`, `created_at`, `outcome` (enum),
  `reason`, `confidence`.
- Persisted via a new `signal_decisions` table + repository in
  `activity/adapters/`, written by the engine through a port so
  `engine/application/` stays adapter-free.
- `TradeEngine._try_enter` / `_enter_for_bot` and
  `OrderService.open_position` record the decision and its outcome instead of
  relying on downstream regex.
- `extract_bot_signals` keeps working for **historical** rows (backfill path)
  but new reads come from the table.
- Human-readable log lines stay — they just stop being the source of truth.

**Done when:** the chart's signal trail is served from `signal_decisions`,
`bot_signals.py` is documented as legacy-only, tests cover each outcome.

## Phase 2 — Veto funnel (structured checks)

**Status:** not started

- Add `checks: tuple[DecisionCheck, ...]` to `SignalDecision` —
  `(name, value, threshold, comparison, passed)`, mirroring the shape already
  used by `TradeRecord.indicators`.
- Split the collapsed `risk_rejected` bucket into distinct outcomes:
  `htf_veto`, `spread_veto`, `rr_gate`, `volatility_guard`, `max_positions`,
  `risk_sizing`, `broker_rejected`, `daily_loss_breaker`, `opened`.
  Note: the chart indexes `SIGNAL_OUTCOME_META[outcome]` unguarded — it must
  be extended in the same change or it will crash.
- New endpoint returning the funnel per bot per period: signals fired →
  passed HTF → passed spread → sized OK → filled, with counts and drop
  reasons.
- Frontend: funnel panel in `features/analytics/`.

**Done when:** a bot's page answers "of 120 signals, why did only 14 trade?"

## Phase 3 — Execution telemetry

**Status:** not started

Add to `TradeRecord` (+ migration, + journal write path):

- `requested_price` and resulting **slippage** (fill vs requested).
- **execution latency** — signal emit → broker ack, milliseconds.
- **broker retcode** on both fills and rejects (e.g. MT5 `10016` invalid
  stops, which silently killed a whole VIX75 fleet before).
- **MFE / MAE** per trade — max favorable / adverse excursion, computed from
  candles while the position is open and finalized on close.

Surface them in `journal/domain/analytics.py`: avg slippage, avg latency,
retcode histogram, and MFE/MAE ratios (are TPs too far? SLs too tight?).

**Done when:** analytics shows cost-per-trade and excursion stats per bot.

## Phase 4 — Backtest realism & live/backtest divergence

**Status:** not started

- Simulate broker constraints in the backtest engine: `stops_level`, min lot,
  lot step, spread widening, and a slippage distribution sampled from the
  real data collected in Phase 3.
- Reject backtest entries that a live broker would reject, and count them.
- A divergence report comparing live vs backtest fills for the same signal
  conditions — systematic gaps mean the simulator is lying or the edge decayed.

**Done when:** an M1 scalp backtest no longer reports trades the broker would
have refused.

## Phase 5 — Metrics, correlation IDs, log hygiene

**Status:** not started

- Prometheus metrics endpoint: engine loop duration, gateway RTT, signals/min,
  veto counts by reason, open positions, WS client count.
- Correlation IDs — extend the existing `ContextVar` pattern in
  `shared/logging/account_context.py` to also carry `signal_id`, so every line
  from signal → sizing → order → fill → journal joins up.
- Structured (JSON) log output alongside the human format.
- Log-level hygiene: routine per-bar chatter moves to DEBUG; INFO becomes
  decisions only.
- Silence alerting: warn when a bot emits no signal for N× its median
  interval (a dead bot currently looks like a quiet market).

**Done when:** `/metrics` scrapes clean and INFO is readable end to end.

## Phase 6 — Regime tagging & walk-forward research

**Status:** not started

- Tag every trade and decision with the market regime at entry: ATR
  percentile bucket, trading session, trend/range classification.
- Regime-split analytics — PF and expectancy per regime, per bot.
- Walk-forward backtesting harness (rolling in-sample/out-of-sample) to
  replace single-window PF numbers, which are very likely overfit
  (e.g. `pob_snd_zones_xauusd` PF 3.70 on one window).
- Cost-as-%-of-gross-edge metric per bot — expected to show M1 scalps
  spending their entire edge on spread + slippage.

**Done when:** each bot's edge is reported per regime, out-of-sample.

---

## Progress log

| Date | Phase | Result |
|---|---|---|
| 2026-08-05 | — | Plan created from code audit. |
