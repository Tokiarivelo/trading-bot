"""Wire schema for the `/backtest` HTTP API. Mirrors `backtest/domain/models.py`;
these endpoints only ever read reports written by `python -m src.backtest.cli`
(see `backtest/reports/writer.py`) — they never run a backtest themselves."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestTradeOut(BaseModel):
    side: str = Field(description="'buy' or 'sell'.")
    volume: float
    open_time: int = Field(description="Epoch seconds UTC.")
    open_price: float
    sl: float | None
    tp: float | None
    close_time: int = Field(description="Epoch seconds UTC.")
    close_price: float
    profit: float
    r_multiple: float | None = Field(
        description="Profit / initial risk in account currency; null if the trade had no SL."
    )


class EquityPointOut(BaseModel):
    time: int = Field(description="Epoch seconds UTC.")
    balance: float


class BacktestReportSummaryOut(BaseModel):
    """One report file's headline stats — used by the report list view."""

    id: str = Field(
        description="Report identifier; fetch full detail at GET /backtest/reports/{id}."
    )
    strategy: str
    symbol: str
    period: str = Field(description="'YYYY-MM:YYYY-MM' as passed to the CLI.")
    trade_count: int
    win_rate: float = Field(description="Fraction of trades with positive profit, 0..1.")
    profit_factor: float | None = Field(
        description="Gross profit / gross loss; null means no losing trades (infinite)."
    )
    max_drawdown_pct: float
    avg_r: float
    worst_losing_streak: int
    starting_balance: float
    ending_balance: float


class BacktestReportDetailOut(BacktestReportSummaryOut):
    """Full report: headline stats plus every trade and the equity curve, for
    the report detail page's trade table and `lightweight-charts` equity plot."""

    trades: list[BacktestTradeOut]
    equity_curve: list[EquityPointOut]
