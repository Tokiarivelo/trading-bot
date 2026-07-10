---
name: refine-bot
description: Apply an AI AnalysisReport's refinement to a strategy — produce the diff, validate in sandbox, and compare backtests before/after.
---

# Refine Bot

Refine a strategy based on the AnalysisReport identified by `$ARGUMENTS`
(report id, or path to a report JSON).

## Steps
1. Load the AnalysisReport (DB via backend CLI, or file) and the current active
   strategy version it refers to.
2. Summarize the report's findings and the proposed refinement to the user.
3. Create the refined file as a NEW version
   (`..._vN+1.py`) — never edit the old version in place.
4. Validate: ruff, pytest, sandbox static validation (import whitelist, AST scan).
5. Backtest old vs new on the same period/symbol; present the comparison table
   (win rate, profit factor, max drawdown, R distribution).
6. Only mark the new version as ready if it improves; the user activates it.

## Must never
- Edit `configs/risk.yaml`, `backend/src/engine/`, or circuit-breaker logic.
- Increase any risk-related parameter embedded in a strategy spec.
- Delete or overwrite the previous strategy version (rollback must stay possible).
