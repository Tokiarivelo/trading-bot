"""Wire schema for the `/backtest` HTTP API. Mirrors `backtest/domain/models.py`;
these endpoints only ever read reports written by `python -m src.backtest.cli`
(see `backtest/reports/writer.py`) — they never run a backtest themselves."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ZoneOut(BaseModel):
    """The supply/demand rectangle the strategy identified before entering
    this trade, for drawing on the chart. Only present for strategies that
    report one (e.g. `pob_price_action_snd`)."""

    kind: str = Field(description="'demand' (buy zone) or 'supply' (sell zone).")
    price_low: float = Field(description="Lower bound of the zone rectangle.")
    price_high: float = Field(description="Upper bound of the zone rectangle.")
    time_start: int = Field(description="Epoch seconds UTC — left edge of the zone rectangle.")
    time_end: int = Field(
        description="Epoch seconds UTC — right edge of the zone rectangle (the entry candle)."
    )


class StructurePointOut(BaseModel):
    """A single labeled swing point from the window the strategy used to
    validate this trade's zone — chart annotation only, not used to gate
    the trade itself."""

    label: str = Field(description="Swing-structure label: 'HH', 'HL', 'LH', or 'LL'.")
    price: float = Field(description="Price of the swing high/low.")
    time: int = Field(description="Epoch seconds UTC of the swing bar.")


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
    zone: ZoneOut | None = Field(
        default=None,
        description="Supply/demand zone this trade was taken from, if the strategy reports one.",
    )
    pattern: str | None = Field(
        default=None,
        description="Confirming candlestick pattern, e.g. 'bullish_engulfing', if reported.",
    )
    structure: list[StructurePointOut] = Field(
        default_factory=list,
        description=(
            "Labeled swing points (HH/HL/LH/LL) from the window the strategy used to "
            "validate this trade's zone, for chart annotation."
        ),
    )


class EquityPointOut(BaseModel):
    time: int = Field(description="Epoch seconds UTC.")
    balance: float


class ActivityLogEntryOut(BaseModel):
    """One decision-trail line captured while replaying — a signal, an HTF
    veto, a risk-sizing rejection, a fill, a circuit breaker — so a report
    with zero trades still explains why, without needing server stdout."""

    time: int = Field(
        description="Epoch seconds UTC — the simulated bot clock (bar close "
        "time) when this was logged, not wall-clock time."
    )
    level: str = Field(description="Python logging level name, e.g. 'INFO', 'WARNING'.")
    logger: str = Field(
        description="Originating logger name, e.g. 'src.engine.application.trade_loop' — "
        "identifies which module made the decision."
    )
    message: str = Field(description="The formatted log message, e.g. why a signal was vetoed.")


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
    min_rr: float = Field(
        default=1.0,
        description="The spread-adjusted minimum reward:risk ratio SpreadGate actually "
        "enforced for this run — configs/symbols/<symbol>.yaml's value, this run's own "
        "min_rr override, or 1.0 (SpreadGate.DEFAULT_MIN_RR) if the symbol has no config "
        "file. A run parameter like starting_balance, not a fixed strategy property — "
        "older report files predating this field default to 1.0.",
    )
    risk_per_trade_pct: float = Field(
        default=0.5,
        description="% of balance risked per trade — configs/risk.yaml's value, or this "
        "run's own override. A run parameter, not a fixed strategy property.",
    )
    daily_loss_limit_pct: float = Field(
        default=2.0,
        description="Circuit breaker: the engine pauses once a trading day's realized loss "
        "reaches this — and never auto-resumes (see RiskManager.record_trade_closed), so a "
        "trade count far lower than the period would suggest often means this tripped early "
        "and the rest of the run saw every entry blocked, not that no more setups occurred.",
    )
    max_open_positions: int = Field(
        default=100, description="Circuit breaker: cap on simultaneous positions for this run."
    )
    max_trades_per_day: int = Field(
        default=8, description="Circuit breaker: cap on entries per trading day for this run."
    )
    consecutive_loss_pause: int = Field(
        default=10,
        description="Circuit breaker: the engine pauses (same never-auto-resumes caveat as "
        "daily_loss_limit_pct) after this many losing trades in a row.",
    )
    min_lot_fallback_enabled: bool = Field(
        default=False,
        description="Whether the broker-minimum-lot sizing fallback was enabled for this "
        "run (see RiskManager.size_position) — configs/risk.yaml's value, this run's own "
        "override, or the live engine override if neither was passed.",
    )
    max_risk_per_trade_pct: float | None = Field(
        default=None,
        description="Ceiling (%) for the minimum-lot fallback's effective risk, for this "
        "run. Only matters when min_lot_fallback_enabled is true. Null means the fallback "
        "(when enabled) used risk_per_trade_pct itself as the ceiling.",
    )


class BacktestReportDetailOut(BacktestReportSummaryOut):
    """Full report: headline stats plus every trade and the equity curve, for
    the report detail page's trade table and `lightweight-charts` equity plot."""

    trades: list[BacktestTradeOut]
    equity_curve: list[EquityPointOut]
    activity_log: list[ActivityLogEntryOut] = Field(
        default_factory=list,
        description="The bot's decision trail during the replay (signals, HTF vetoes, "
        "sizing rejections, fills, circuit breakers), oldest first — explains a "
        "zero-trade report. Older report files predating this field return an "
        "empty list.",
    )


class BacktestReportListOut(BaseModel):
    """One page of the saved-report list, newest first."""

    items: list[BacktestReportSummaryOut] = Field(
        description="Report summaries for this page, newest first."
    )
    total: int = Field(description="Total number of saved report files, across all pages.")
    limit: int = Field(description="Page size that was applied.")
    offset: int = Field(description="Number of newest reports skipped before this page.")
