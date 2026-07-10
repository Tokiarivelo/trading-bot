---
name: new-strategy
description: Scaffold a new trading strategy from a StrategySpec or a plain description — correct Strategy protocol, sandbox-safe imports, unit test stub, registry entry, and a first backtest.
---

# New Strategy

Create a strategy file in `backend/src/strategies/generated/` from the spec or
description given in `$ARGUMENTS`.

## Steps
1. If `$ARGUMENTS` is a path to a StrategySpec (JSON/YAML), load it; otherwise
   draft a StrategySpec first (symbols, entry timeframe M5, HTF confirmation
   rules, indicators, entry/exit rules, params) and show it for confirmation.
2. Write `backend/src/strategies/generated/<symbol>_<name>_v1.py`:
   - Implements the `Strategy` protocol from `backend/src/strategies/domain/`.
   - Imports ONLY: `math`, `statistics`, `numpy`, `pandas`, and strategy domain types.
   - Pure function of `MarketContext` → `Signal | None`. No I/O of any kind.
3. Write a unit test in `backend/tests/unit/strategies/` using fixture candles.
4. Register the strategy in the registry.
5. Run validation: `uv run ruff check`, `uv run pytest`, then the sandbox static
   validation, then a backtest via the backtest CLI once it exists (Phase 5).
6. Report: spec summary, file path, test result, backtest metrics.

## Must never
- Touch `configs/risk.yaml` or `backend/src/engine/`.
- Add imports outside the whitelist.
- Activate the strategy for live trading — activation is a user action in the UI.
