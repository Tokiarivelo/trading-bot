"""Confirms the zone/pattern/structure fields a strategy's Signal reports
travel through PositionOpened -> BacktestBookkeeper -> BacktestTrade intact —
the plumbing added so backtest chart annotations (zone rectangle, SL,
pattern, swing structure) have real data to draw."""

from datetime import UTC, datetime

import pytest

from src.backtest.adapters.bookkeeper import BacktestBookkeeper
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps
from src.shared.events.definitions import PositionClosed, PositionOpened

CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=5,
    max_trades_per_day=8,
    consecutive_loss_pause=3,
)

T_OPEN = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
T_CLOSE = datetime(2025, 1, 1, 11, 0, tzinfo=UTC)
ZONE_START = datetime(2025, 1, 1, 9, 0, tzinfo=UTC)


def make_bookkeeper() -> BacktestBookkeeper:
    clock_box = {"now": T_OPEN}
    return BacktestBookkeeper(
        starting_balance=10_000.0,
        risk_manager=RiskManager(caps=CAPS, timezone="UTC"),
        contract_size=1.0,
        clock=lambda: clock_box["now"],
    ), clock_box


@pytest.mark.asyncio
async def test_zone_pattern_structure_survive_open_to_close():
    bookkeeper, clock_box = make_bookkeeper()

    await bookkeeper.on_position_opened(
        PositionOpened(
            symbol="Volatility 75 Index",
            position_id="1",
            side="buy",
            volume=1.0,
            price=100.0,
            sl=98.0,
            tp=104.0,
            spread_points=20,
            zone_kind="demand",
            zone_price_low=99.7,
            zone_price_high=100.3,
            zone_time_start=ZONE_START,
            zone_time_end=T_OPEN,
            pattern="bullish_engulfing",
            structure=(("HH", 105.0, ZONE_START), ("LL", 95.0, T_OPEN)),
        )
    )
    clock_box["now"] = T_CLOSE
    await bookkeeper.on_position_closed(
        PositionClosed(
            symbol="Volatility 75 Index", position_id="1", close_price=103.0, profit=300.0
        )
    )

    trade = bookkeeper.trades[0]
    assert trade.zone is not None
    assert trade.zone.kind == "demand"
    assert trade.zone.price_low == 99.7
    assert trade.zone.price_high == 100.3
    assert trade.zone.time_start == ZONE_START
    assert trade.zone.time_end == T_OPEN
    assert trade.pattern == "bullish_engulfing"
    assert trade.structure == (("HH", 105.0, ZONE_START), ("LL", 95.0, T_OPEN))


@pytest.mark.asyncio
async def test_no_zone_defaults_to_none():
    bookkeeper, clock_box = make_bookkeeper()

    await bookkeeper.on_position_opened(
        PositionOpened(
            symbol="XAUUSD",
            position_id="2",
            side="sell",
            volume=1.0,
            price=2400.0,
            sl=2410.0,
            tp=2380.0,
            spread_points=25,
        )
    )
    clock_box["now"] = T_CLOSE
    await bookkeeper.on_position_closed(
        PositionClosed(symbol="XAUUSD", position_id="2", close_price=2380.0, profit=200.0)
    )

    trade = bookkeeper.trades[0]
    assert trade.zone is None
    assert trade.pattern is None
    assert trade.structure == ()
