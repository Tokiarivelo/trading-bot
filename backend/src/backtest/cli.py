"""Backtest CLI (Phase 5).

    uv run python -m src.backtest.cli <strategy> <symbol> <period>
    uv run python -m src.backtest.cli breakout_v1 XAUUSD 2025-01:2025-06

Run from `backend/`. Reads candle history already persisted by
`market_data.CandleRepository` (via `POST /market-data/backfill`) — if none
exists for the requested range, exits with a message telling you to backfill
first, per `.claude/skills/backtest/SKILL.md`.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.backtest.application.period import InvalidPeriod
from src.backtest.application.run_backtest import NoHistoryError, NoSymbolSpecError, run_backtest
from src.backtest.reports.writer import render_summary, write_report
from src.shared.config.settings import Settings


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m src.backtest.cli <strategy> <symbol> <period>", file=sys.stderr)
        print(
            "e.g.:  python -m src.backtest.cli breakout_v1 XAUUSD 2025-01:2025-06",
            file=sys.stderr,
        )
        return 2

    strategy_name, symbol, period = argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()

    try:
        report = asyncio.run(
            run_backtest(
                strategy_name,
                symbol,
                period,
                database_url=settings.database_url,
            )
        )
    except (InvalidPeriod, NoHistoryError, NoSymbolSpecError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    path = write_report(report)
    print(render_summary(report))
    print(f"\nFull report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
