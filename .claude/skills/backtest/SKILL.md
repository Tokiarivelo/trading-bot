---
name: backtest
description: Run a backtest for a strategy on a symbol and period, then summarize win rate, profit factor, max drawdown, and equity curve.
---

# Backtest

Run a backtest as specified in `$ARGUMENTS` (expected: `<strategy> <symbol> <period>`,
e.g. `xauusd_breakout_v1 XAUUSD 2025-01:2025-06`).

## Steps
1. Ensure historical data for the symbol/period exists in the DB; if missing,
   run the historical download job first (Phase 1+).
2. Run: `uv run python -m src.backtest.cli <strategy> <symbol> <period>`
   from `backend/` (CLI lands in Phase 5 — if it doesn't exist yet, say so and
   stop rather than improvising).
3. Read the generated report from `backend/src/backtest/reports/`.
4. Summarize: trades, win rate, profit factor, max drawdown, avg R, worst
   losing streak, and whether spread modeling was enabled.

## Must never
- Run against a live account. Backtests use the replay adapter + paper broker only.
