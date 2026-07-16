---
name: backtest
description: Run a backtest for a strategy on a symbol and period, then summarize win rate, profit factor, max drawdown, and equity curve.
---

# Backtest

Run a backtest as specified in `$ARGUMENTS` (expected: `<strategy> <symbol> <period>`,
e.g. `breakout_v1 XAUUSD 2025-01:2025-06`). `period` is always `YYYY-MM:YYYY-MM`
(end month inclusive, parsed as `[start, end)` — see
`backend/src/backtest/application/period.py`).

## Which entry point to use

There are two ways to run a backtest, and they resolve `<strategy>`
differently — pick based on what the strategy's status actually is
(`GET /strategies/versions` or `GET /backtest/bots` tells you):

- **CLI** (`uv run python -m src.backtest.cli <strategy> <symbol> <period>`
  from `backend/`, or `make backtest strategy=... symbol=... period=...` from
  the repo root) — resolves `<strategy>` as a **family name**. Only works for
  the four hardcoded baselines (`breakout_v1`, `trend_structure_v1`,
  `trend_structure_v2`, `mean_reversion_v1`) or a strategy whose family
  currently has an **ACTIVE** `StrategyVersion`. It does **not** auto-backfill
  — missing history raises `NoHistoryError` and the CLI just prints the error.
  Report is written straight to
  `backend/src/backtest/reports/<strategy>_<symbol>_<period_with_underscores>.json`.
- **API job** (what the UI's "Run Backtest" panel uses) — resolves `<strategy>`
  as a **version id** (UUID) instead, so it also works for a strategy that's
  only `VALIDATED` (e.g. one `new-strategy` just created but nobody has
  activated yet). It also auto-backfills missing history from the gateway
  before replaying.
  ```bash
  curl -s -X POST http://localhost:8000/backtest/run \
    -H 'content-type: application/json' \
    -d '{"strategy_id":"<family_name_or_version_id>","symbol":"<symbol>","period":"<period>"}'
  # -> {"job_id": "...", "status": "pending"}
  curl -s http://localhost:8000/backtest/run/<job_id>   # poll until status == "done"
  curl -s http://localhost:8000/backtest/reports/<report_id>
  ```
  `strategy_id` also accepts the four baseline family-name literals directly.
  Optional overrides on the same request: `starting_balance`,
  `min_lot_fallback_enabled`, `max_risk_per_trade_pct`, `min_rr` — useful for
  testing whether a strategy only fails because it's borderline on the
  symbol's spread-adjusted RR floor (`configs/symbols/<symbol>.yaml`'s
  `min_rr`), without editing that file.
  Requires the backend running (`make dev-backend`).

If unsure which applies, default to the API job path — it's a strict superset
(handles both statuses, auto-backfills) and it's what the product itself uses.

## Steps
1. Check whether history already covers `<period>` for `<symbol>`. If using
   the CLI path and it isn't there yet, backfill first:
   `POST /market-data/backfill` with `{"symbols": ["<symbol>"], "start": "<period start>"}`
   (paginates backward from the gateway until it reaches `start`; also
   snapshots the symbol's broker facts into `symbol_specs`, which is what
   lets a backtest replay a symbol that has no hand-authored
   `configs/symbols/<symbol>.yaml`). The API job path does this
   automatically on `NoHistoryError` — no separate call needed there.
2. Run the backtest via whichever entry point step "Which entry point to use"
   selected.
3. Read the report: `backend/src/backtest/reports/<report_id>.json`, or
   `GET /backtest/reports/<report_id>` for the API path (same file, served as
   `BacktestReportDetailOut`: trades, equity_curve, activity_log).
4. Summarize: trade count, win rate, profit factor (reported as `"inf"` when
   there are zero losing trades), max drawdown %, avg R, worst losing streak,
   starting vs ending balance. If trade count is 0, say so explicitly and
   check the activity log for veto/rejection reasons (spread-adjusted RR
   floor, HTF confirmation gating, sizing rejections) before concluding "no
   setups occurred" — a strategy whose RR barely clears `min_rr` gets vetoed
   on every signal, which looks identical to "found nothing" without reading
   the log.

## Must never
- Run against a live account — both paths replay through `PaperBroker` +
  the replay market-data adapter only; the only live-gateway contact is the
  auto-backfill's read-only history/`symbol_info` fetch.
