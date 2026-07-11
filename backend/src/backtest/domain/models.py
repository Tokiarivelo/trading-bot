"""Backtest domain: a completed trade, an equity point, and the final report.

Pure values — no I/O. Deliberately not the `journal` module's `TradeRecord`:
a backtest doesn't touch the journal DB and modules don't reach into each
other's internals (see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class BacktestTrade:
    side: str  # "buy" | "sell"
    volume: float
    open_time: datetime
    open_price: float
    sl: float | None
    tp: float | None
    close_time: datetime
    close_price: float
    profit: float
    r_multiple: float | None  # profit / initial risk in account currency; None if sl was unset


@dataclass(frozen=True, kw_only=True)
class EquityPoint:
    time: datetime
    balance: float


@dataclass(frozen=True, kw_only=True)
class BacktestReport:
    strategy: str
    symbol: str
    period: str
    starting_balance: float
    ending_balance: float
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    avg_r: float
    worst_losing_streak: int
