"""Phase 5 end-to-end: a synthetic M5 candle history containing two clean
breakout episodes (mirrors test_phase4_engine_flow.py's fixture style) is
seeded into a temp SQLite DB and replayed through `run_backtest`, driving the
exact same TradeEngine/RiskManager/PositionManager/OrderService pipeline live
trading uses. Confirms one trade closes via TP and the other via SL, and the
report's derived metrics match by direct calculation.

Uses the real `configs/` (risk.yaml, symbols/xauusd.yaml, app.yaml) since
those are the project's actual, checked-in trading config — no fixture
config needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backtest.application.run_backtest import run_backtest
from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Candle, Timeframe
from src.shared.db.base import Base

M5_STEP = timedelta(minutes=5)
START = datetime(2025, 1, 1, tzinfo=UTC)


def m5(i: int, *, open: float, high: float, low: float, close: float, spread: int = 25) -> Candle:
    return Candle(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        time=START + i * M5_STEP,
        open=open,
        high=high,
        low=low,
        close=close,
        tick_volume=1000,
        spread_points=spread,
    )


def build_m5_candles() -> list[Candle]:
    bars: list[Candle] = []
    # Episode 1: 20-bar flat range, a bullish breakout, then a bar whose high
    # clears the strategy's TP.
    bars += [m5(i, open=2400.0, high=2401.0, low=2399.0, close=2400.0) for i in range(20)]
    bars.append(m5(20, open=2401.0, high=2411.0, low=2400.5, close=2410.0))  # BUY breakout
    # Wick reaches the TP (2434.325) but the close stays below bar 20's high
    # (2411) so this bar doesn't *also* look like a fresh breakout signal.
    bars.append(m5(21, open=2410.0, high=2440.0, low=2405.0, close=2408.0))  # clears TP

    # Episode 2: a fresh 20-bar flat range, a bearish breakout, then a bar
    # whose high clears the strategy's SL (stopping the short out at a loss).
    bars += [m5(22 + i, open=2440.0, high=2441.0, low=2439.0, close=2440.0) for i in range(20)]
    bars.append(m5(42, open=2439.0, high=2439.5, low=2429.0, close=2430.0))  # SELL breakout
    bars.append(m5(43, open=2430.0, high=2445.0, low=2428.0, close=2432.0))  # clears SL
    return bars


def build_htf_candles(timeframe: Timeframe, step: timedelta, count: int = 5) -> list[Candle]:
    """Deliberately fewer bars than mtf_confirm's slow EMA period needs, so
    HTF confirmation is skipped (insufficient history) rather than vetoing —
    same trick test_phase4_engine_flow.py uses."""
    return [
        Candle(
            symbol="XAUUSD",
            timeframe=timeframe,
            time=START - (count - i) * step,
            open=2400.0,
            high=2401.0,
            low=2399.0,
            close=2400.5,
            tick_volume=1000,
            spread_points=25,
        )
        for i in range(count)
    ]


@pytest.fixture
def database_url(tmp_path) -> str:
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = CandleRepository(session_factory)
    repository.upsert_many(build_m5_candles())
    repository.upsert_many(build_htf_candles(Timeframe.H1, timedelta(hours=1)))
    repository.upsert_many(build_htf_candles(Timeframe.H4, timedelta(hours=4)))
    return url


async def test_backtest_closes_one_trade_via_tp_and_one_via_sl(database_url):
    report = await run_backtest(
        "breakout_v1", "XAUUSD", "2025-01:2025-01", database_url=database_url
    )

    assert len(report.trades) == 2
    tp_trade, sl_trade = report.trades

    assert tp_trade.side == "buy"
    assert tp_trade.profit > 0
    assert tp_trade.r_multiple == pytest.approx(2.2, rel=1e-3)  # breakout_v1's TP_RR

    assert sl_trade.side == "sell"
    assert sl_trade.profit < 0
    assert sl_trade.r_multiple == pytest.approx(-1.0, rel=1e-3)

    assert report.win_rate == pytest.approx(0.5)
    assert report.worst_losing_streak == 1
    assert report.ending_balance == pytest.approx(
        report.starting_balance + tp_trade.profit + sl_trade.profit
    )
    assert report.profit_factor == pytest.approx(tp_trade.profit / -sl_trade.profit)
    assert report.avg_r == pytest.approx((tp_trade.r_multiple + sl_trade.r_multiple) / 2)


async def test_backtest_raises_when_no_history(database_url):
    from src.backtest.application.run_backtest import NoHistoryError

    with pytest.raises(NoHistoryError):
        await run_backtest("breakout_v1", "XAUUSD", "2030-01:2030-01", database_url=database_url)


async def test_backtest_rejects_unknown_strategy(database_url):
    with pytest.raises(ValueError, match="unknown strategy"):
        await run_backtest("not_a_strategy", "XAUUSD", "2025-01:2025-01", database_url=database_url)


async def test_backtest_rejects_symbol_the_strategy_does_not_trade(database_url):
    with pytest.raises(ValueError, match="does not trade"):
        await run_backtest("breakout_v1", "EURUSD", "2025-01:2025-01", database_url=database_url)
