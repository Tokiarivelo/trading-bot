"""Trade analytics: pure aggregation over journaled trades (§6.8 extension).

Computes per-symbol and per-bot performance stats and equity curves from
`TradeRecord` lists — no I/O, no framework imports. Backs the analytics
dashboard used to compare bots and find the best-performing approach.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.journal.domain.models import TradeAnalyticsRecord, TradeRecord

# Both aggregation functions only touch the fields the two types share
# (id, symbol, volume, open_time, close_time, profit, skill,
# strategy_version, is_open) — callers may pass either the full
# `TradeRecord` or the slim `TradeAnalyticsRecord` projection.
AnalyticsRecord = TradeRecord | TradeAnalyticsRecord


@dataclass(frozen=True, kw_only=True)
class EquityPoint:
    """One step of a bot's cumulative-profit curve, in close order."""

    trade_id: str
    close_time: int  # epoch seconds UTC
    profit: float
    cumulative_profit: float


@dataclass(frozen=True, kw_only=True)
class SymbolAnalytics:
    """Aggregate performance of every trade (any bot, or manual) on one symbol."""

    symbol: str
    trade_count: int
    open_count: int
    closed_count: int
    win_count: int
    loss_count: int
    breakeven_count: int
    win_rate: float  # 0..1, over closed trades
    total_profit: float
    gross_profit: float
    gross_loss: float  # positive number
    profit_factor: float | None  # None when there are no losing trades yet
    avg_win: float
    avg_loss: float  # positive number
    avg_profit_per_trade: float
    largest_win: float
    largest_loss: float  # negative or zero
    total_volume: float
    bot_count: int  # distinct bots (skills) that have traded this symbol
    first_trade_time: int | None
    last_trade_time: int | None


@dataclass(frozen=True, kw_only=True)
class BotAnalytics:
    """Aggregate performance of one bot (skill) across its trades, plus its
    equity curve — the unit the analytics dashboard ranks bots by."""

    skill: str
    bot_name: str  # last segment of `skill`, e.g. 'breakout_v1'
    symbol: str
    strategy_version: str | None  # most recent trade's, e.g. 'breakout_v1:v1'
    trade_count: int
    open_count: int
    closed_count: int
    win_count: int
    loss_count: int
    breakeven_count: int
    win_rate: float
    total_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    avg_win: float
    avg_loss: float
    expectancy: float  # avg profit per closed trade
    largest_win: float
    largest_loss: float
    max_drawdown: float  # peak-to-trough of cumulative profit, positive number
    avg_trade_duration_seconds: float | None
    first_trade_time: int | None
    last_trade_time: int | None
    equity_curve: tuple[EquityPoint, ...]
    # ── Execution quality (OBSERVABILITY_PLAN.md Phase 3) ──────────────────
    # Every average here is taken over the trades that actually carry the
    # measurement; trades journaled before Phase 3 (all-None columns) are
    # skipped rather than counted as zero, which would silently drag a bot's
    # average slippage toward 0 the longer its history is.
    avg_slippage: float | None
    """Mean signed slippage in price units, positive = the fills cost the
    trader. None when no trade of this bot was measured."""
    measured_slippage_count: int
    """How many of this bot's trades the `avg_slippage` mean is over — the
    denominator, so a -0.02 average off two fills isn't read as a verdict."""
    avg_execution_latency_ms: float | None
    """Mean signal-emit → broker-ack milliseconds. None when unmeasured."""
    retcode_histogram: tuple[tuple[int, int], ...]
    """`(broker_retcode, count)` over this bot's fills that reported one,
    most frequent first. MT5 10009 is a clean deal; anything else recurring
    here is a systematic execution problem."""
    avg_mfe: float | None
    """Mean maximum favorable excursion (price units) over closed trades."""
    avg_mae: float | None
    """Mean maximum adverse excursion (price units) over closed trades."""
    mfe_mae_ratio: float | None
    """avg_mfe / avg_mae. None when avg_mae is 0 or unmeasured."""
    avg_mfe_on_losers: float | None
    """Mean MFE across *losing* closed trades — "how far in profit was this
    trade before it died". Large relative to the bot's average win is the
    signature of a take-profit parked past where price actually turns."""
    avg_mae_on_winners: float | None
    """Mean MAE across *winning* closed trades — "how much heat a winner
    took". Approaching the bot's stop distance means the stops are as tight
    as they can get before winners start being stopped out."""


def _closed(trades: list[AnalyticsRecord]) -> list[AnalyticsRecord]:
    return [t for t in trades if not t.is_open]


def _wins_losses_breakeven(
    closed: list[AnalyticsRecord],
) -> tuple[list[AnalyticsRecord], list[AnalyticsRecord], list[AnalyticsRecord]]:
    wins = [t for t in closed if (t.profit or 0.0) > 0]
    losses = [t for t in closed if (t.profit or 0.0) < 0]
    breakeven = [t for t in closed if (t.profit or 0.0) == 0]
    return wins, losses, breakeven


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    """None (rather than infinity) when there are no losing trades yet —
    infinity doesn't round-trip through standard JSON."""
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def _equity_curve(closed: list[AnalyticsRecord]) -> tuple[EquityPoint, ...]:
    ordered = sorted(closed, key=lambda t: t.close_time)  # close_time set on every closed trade
    points = []
    running = 0.0
    for t in ordered:
        running += t.profit or 0.0
        points.append(
            EquityPoint(
                trade_id=t.id,
                close_time=int(t.close_time.timestamp()),  # type: ignore[union-attr]
                profit=t.profit or 0.0,
                cumulative_profit=running,
            )
        )
    return tuple(points)


def _max_drawdown(equity_curve: tuple[EquityPoint, ...]) -> float:
    peak = 0.0
    max_dd = 0.0
    for point in equity_curve:
        peak = max(peak, point.cumulative_profit)
        max_dd = max(max_dd, peak - point.cumulative_profit)
    return max_dd


def _mean(values: list[float]) -> float | None:
    """None (not 0.0) for an empty sample — "never measured" and "measured,
    averages zero" are different answers, and only one of them is a reason to
    go looking for a bug in the telemetry."""
    return sum(values) / len(values) if values else None


def _measured(trades: list[AnalyticsRecord], attribute: str) -> list[float]:
    """The non-None readings of one telemetry attribute, in trade order."""
    return [
        float(getattr(t, attribute))
        for t in trades
        if getattr(t, attribute, None) is not None
    ]


def _retcode_histogram(trades: list[AnalyticsRecord]) -> tuple[tuple[int, int], ...]:
    counts: dict[int, int] = defaultdict(int)
    for t in trades:
        code = getattr(t, "broker_retcode", None)
        if code is not None:
            counts[int(code)] += 1
    # Most frequent first, code ascending as the tiebreak so the order is
    # stable across calls (dashboards diff these lists).
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def compute_symbol_analytics(trades: list[AnalyticsRecord]) -> list[SymbolAnalytics]:
    """One entry per distinct symbol, ranked by total realized profit."""
    by_symbol: dict[str, list[AnalyticsRecord]] = defaultdict(list)
    for t in trades:
        by_symbol[t.symbol].append(t)

    results = []
    for symbol, symbol_trades in by_symbol.items():
        closed = _closed(symbol_trades)
        wins, losses, _breakeven = _wins_losses_breakeven(closed)
        gross_profit = sum(t.profit or 0.0 for t in wins)
        gross_loss = -sum(t.profit or 0.0 for t in losses)
        total_profit = sum(t.profit or 0.0 for t in closed)
        open_times = [int(t.open_time.timestamp()) for t in symbol_trades]
        results.append(
            SymbolAnalytics(
                symbol=symbol,
                trade_count=len(symbol_trades),
                open_count=len(symbol_trades) - len(closed),
                closed_count=len(closed),
                win_count=len(wins),
                loss_count=len(losses),
                breakeven_count=len(_breakeven),
                win_rate=len(wins) / len(closed) if closed else 0.0,
                total_profit=total_profit,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                profit_factor=_profit_factor(gross_profit, gross_loss),
                avg_win=gross_profit / len(wins) if wins else 0.0,
                avg_loss=gross_loss / len(losses) if losses else 0.0,
                avg_profit_per_trade=total_profit / len(closed) if closed else 0.0,
                largest_win=max((t.profit or 0.0 for t in wins), default=0.0),
                largest_loss=min((t.profit or 0.0 for t in losses), default=0.0),
                total_volume=sum(t.volume for t in symbol_trades),
                bot_count=len({t.skill for t in symbol_trades if t.skill}),
                first_trade_time=min(open_times) if open_times else None,
                last_trade_time=max(open_times) if open_times else None,
            )
        )
    return sorted(results, key=lambda s: s.total_profit, reverse=True)


def compute_bot_analytics(trades: list[AnalyticsRecord]) -> list[BotAnalytics]:
    """One entry per distinct bot (`skill`), ranked by total realized profit.
    Trades with no skill (manual/API-placed) are excluded — they aren't
    attributable to any bot's performance."""
    by_skill: dict[str, list[AnalyticsRecord]] = defaultdict(list)
    for t in trades:
        if t.skill:
            by_skill[t.skill].append(t)

    results = []
    for skill, skill_trades in by_skill.items():
        closed = _closed(skill_trades)
        wins, losses, _breakeven = _wins_losses_breakeven(closed)
        gross_profit = sum(t.profit or 0.0 for t in wins)
        gross_loss = -sum(t.profit or 0.0 for t in losses)
        total_profit = sum(t.profit or 0.0 for t in closed)
        equity_curve = _equity_curve(closed)
        durations = [
            (t.close_time - t.open_time).total_seconds() for t in closed if t.close_time
        ]
        open_times = [int(t.open_time.timestamp()) for t in skill_trades]
        latest_trade = max(skill_trades, key=lambda t: t.open_time)
        slippages = _measured(skill_trades, "slippage")
        avg_mfe = _mean(_measured(closed, "mfe"))
        avg_mae = _mean(_measured(closed, "mae"))
        results.append(
            BotAnalytics(
                skill=skill,
                bot_name=skill.rsplit("/", 1)[-1],
                symbol=latest_trade.symbol,
                strategy_version=latest_trade.strategy_version,
                trade_count=len(skill_trades),
                open_count=len(skill_trades) - len(closed),
                closed_count=len(closed),
                win_count=len(wins),
                loss_count=len(losses),
                breakeven_count=len(_breakeven),
                win_rate=len(wins) / len(closed) if closed else 0.0,
                total_profit=total_profit,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                profit_factor=_profit_factor(gross_profit, gross_loss),
                avg_win=gross_profit / len(wins) if wins else 0.0,
                avg_loss=gross_loss / len(losses) if losses else 0.0,
                expectancy=total_profit / len(closed) if closed else 0.0,
                largest_win=max((t.profit or 0.0 for t in wins), default=0.0),
                largest_loss=min((t.profit or 0.0 for t in losses), default=0.0),
                max_drawdown=_max_drawdown(equity_curve),
                avg_trade_duration_seconds=sum(durations) / len(durations) if durations else None,
                first_trade_time=min(open_times) if open_times else None,
                last_trade_time=max(open_times) if open_times else None,
                equity_curve=equity_curve,
                avg_slippage=_mean(slippages),
                measured_slippage_count=len(slippages),
                avg_execution_latency_ms=_mean(
                    _measured(skill_trades, "execution_latency_ms")
                ),
                retcode_histogram=_retcode_histogram(skill_trades),
                avg_mfe=avg_mfe,
                avg_mae=avg_mae,
                mfe_mae_ratio=(
                    avg_mfe / avg_mae
                    if avg_mfe is not None and avg_mae is not None and avg_mae > 0
                    else None
                ),
                avg_mfe_on_losers=_mean(_measured(losses, "mfe")),
                avg_mae_on_winners=_mean(_measured(wins, "mae")),
            )
        )
    return sorted(results, key=lambda b: b.total_profit, reverse=True)
