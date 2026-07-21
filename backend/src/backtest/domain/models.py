"""Backtest domain: a completed trade, an equity point, and the final report.

Pure values — no I/O. Deliberately not the `journal` module's `TradeRecord`:
a backtest doesn't touch the journal DB and modules don't reach into each
other's internals (see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class BacktestZone:
    """A supply/demand rectangle the strategy identified before entering —
    chart-annotation data. Kept local to this module (not importing
    strategies.domain.models.PriceZone) so backtest doesn't reach into
    another module's internals; see CLAUDE.md."""

    kind: str  # "demand" | "supply"
    price_low: float
    price_high: float
    time_start: datetime
    time_end: datetime


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
    zone: BacktestZone | None = None
    pattern: str | None = None  # confirming candlestick pattern, e.g. "bullish_engulfing"
    structure: tuple[tuple[str, float, datetime], ...] = ()
    """Swing points as (label, price, time), label one of HH/HL/LH/LL."""


@dataclass(frozen=True, kw_only=True)
class BacktestSignal:
    """One strategy signal emitted during the replay — including the ones
    that never became trades. Extracted from the engine's decision-trail log
    lines (see `application/signals.py`), so the report can show every valid
    setup the strategy saw and what the engine did with it."""

    time: datetime  # simulated bot clock (the M5 bar's close time)
    direction: str  # "buy" | "sell"
    outcome: str  # "opened" | "htf_veto" | "risk_rejected" | "spread_veto" | "skipped"
    reason: str  # the strategy's own Signal.reason (pattern, zone, entry/sl/tp lines)


@dataclass(frozen=True, kw_only=True)
class EquityPoint:
    time: datetime
    balance: float


@dataclass(frozen=True, kw_only=True)
class ActivityLogEntry:
    """One decision-trail line captured from the engine/broker/risk-manager's
    own `logging` calls while replaying — signals, HTF vetoes, sizing
    rejections, fills, circuit breakers — so a report with zero trades still
    explains why, without needing the server's stdout at the time it ran."""

    time: datetime  # simulated bot clock (the M5 bar's close time), not wall clock
    level: str  # "INFO" | "WARNING" | "ERROR"
    logger: str  # originating logger name, e.g. "src.engine.application.trade_loop"
    message: str


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
    activity_log: tuple[ActivityLogEntry, ...] = ()
    # Every signal the strategy emitted (taken or vetoed), oldest first —
    # empty for report files predating this field.
    signals: tuple[BacktestSignal, ...] = ()
    # The spread-adjusted minimum reward:risk ratio SpreadGate actually
    # enforced for this run — configs/symbols/<symbol>.yaml's value, the
    # run's own min_rr override, or SpreadGate.DEFAULT_MIN_RR if the symbol
    # has no config file at all. Recorded per-report since it's a run
    # parameter (like starting_balance), not a fixed strategy property.
    min_rr: float = 1.0
    # The full RiskCaps actually enforced for this run — configs/risk.yaml's
    # values, any of this run's own min_lot_fallback_enabled/
    # max_risk_per_trade_pct overrides, or the live engine override if
    # neither was passed. Recorded per-report for the same reason min_rr is:
    # it's a run parameter that can change what the report's trade count
    # means (e.g. explains a circuit-breaker pause cutting a run short — see
    # RiskManager.record_trade_closed, which never auto-resumes).
    risk_per_trade_pct: float = 0.5
    daily_loss_limit_pct: float = 2.0
    max_open_positions: int = 100
    max_trades_per_day: int = 8
    consecutive_loss_pause: int = 10
    min_lot_fallback_enabled: bool = False
    max_risk_per_trade_pct: float | None = None
