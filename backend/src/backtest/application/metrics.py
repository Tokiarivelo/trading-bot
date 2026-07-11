"""Pure metrics over a completed trade list — no I/O, unit-tested directly
against synthetic trades (no need to run a full backtest)."""

from __future__ import annotations

from src.backtest.domain.models import BacktestTrade, EquityPoint


def win_rate(trades: tuple[BacktestTrade, ...]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.profit > 0)
    return wins / len(trades)


def profit_factor(trades: tuple[BacktestTrade, ...]) -> float:
    gross_profit = sum(t.profit for t in trades if t.profit > 0)
    gross_loss = -sum(t.profit for t in trades if t.profit < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def max_drawdown_pct(equity_curve: tuple[EquityPoint, ...]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0].balance
    worst = 0.0
    for point in equity_curve:
        peak = max(peak, point.balance)
        if peak > 0:
            worst = max(worst, (peak - point.balance) / peak * 100)
    return worst


def avg_r(trades: tuple[BacktestTrade, ...]) -> float:
    r_values = [t.r_multiple for t in trades if t.r_multiple is not None]
    if not r_values:
        return 0.0
    return sum(r_values) / len(r_values)


def worst_losing_streak(trades: tuple[BacktestTrade, ...]) -> int:
    worst = 0
    current = 0
    for t in trades:
        if t.profit < 0:
            current += 1
            worst = max(worst, current)
        else:
            current = 0
    return worst
