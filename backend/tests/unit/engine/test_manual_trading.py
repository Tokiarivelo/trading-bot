from datetime import UTC, datetime

import pytest

from src.broker.domain.trading import (
    ExecutionResult,
    OrderRejected,
    OrderType,
    PendingOrder,
    Position,
    Side,
)
from src.engine.application.manual_trading import ManualTradeGate
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps

NOW = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)

CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=2,
    max_trades_per_day=8,
    consecutive_loss_pause=3,
)


class FakeOrderService:
    def __init__(self, open_positions: list[Position] | None = None) -> None:
        self._open_positions = open_positions or []
        self.opened: list = []
        self.pending_placed: list = []

    async def get_positions(self, symbol=None):
        return list(self._open_positions)

    async def open_position(self, symbol, side, volume, sl=None, tp=None, comment=""):
        self.opened.append((symbol, side, volume, sl, tp, comment))
        return ExecutionResult(
            ticket=1,
            symbol=symbol,
            side=side,
            volume=volume,
            price=2400.0,
            sl=sl,
            tp=tp,
            time=NOW,
            spread_points=10,
            comment=comment,
        )

    async def place_pending_order(
        self, symbol, side, order_type, volume, price, sl=None, tp=None, comment=""
    ):
        self.pending_placed.append((symbol, side, order_type, volume, price, sl, tp, comment))
        return PendingOrder(
            ticket=2,
            symbol=symbol,
            side=side,
            order_type=order_type,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            placed_time=NOW,
            comment=comment,
        )


def _position(ticket=1) -> Position:
    return Position(
        ticket=ticket,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=2390.0,
        tp=2420.0,
        open_time=NOW,
        profit=0.0,
    )


def make_gate(open_positions=None, caps=CAPS):
    risk_manager = RiskManager(caps=caps, timezone="UTC")
    order_service = FakeOrderService(open_positions)
    gate = ManualTradeGate(order_service, risk_manager, clock=lambda: NOW)
    return gate, order_service, risk_manager


async def test_open_position_approved_fills_and_records_trade():
    gate, order_service, risk_manager = make_gate()
    result = await gate.open_position("XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0)
    assert result.ticket == 1
    assert len(order_service.opened) == 1
    assert risk_manager.status.trades_today == 1


async def test_open_position_rejected_at_max_open_positions():
    gate, order_service, risk_manager = make_gate(open_positions=[_position(1), _position(2)])
    with pytest.raises(OrderRejected, match="max open positions"):
        await gate.open_position("XAUUSD", Side.BUY, 0.1)
    assert order_service.opened == []
    assert risk_manager.status.trades_today == 0


async def test_open_position_rejected_while_paused():
    gate, order_service, risk_manager = make_gate()
    risk_manager.kill("test pause")
    with pytest.raises(OrderRejected, match="engine paused"):
        await gate.open_position("XAUUSD", Side.BUY, 0.1)
    assert order_service.opened == []


async def test_place_pending_order_allowed_at_max_open_positions():
    # Placement only checks pause state, not max_open_positions/max_trades —
    # those are re-checked when the order actually fills.
    gate, order_service, _ = make_gate(open_positions=[_position(1), _position(2)])
    result = await gate.place_pending_order(
        "XAUUSD", Side.BUY, OrderType.LIMIT, 0.1, 2395.0, sl=2390.0, tp=2415.0
    )
    assert result.ticket == 2
    assert len(order_service.pending_placed) == 1


async def test_place_pending_order_rejected_while_paused():
    gate, order_service, risk_manager = make_gate()
    risk_manager.kill("test pause")
    with pytest.raises(OrderRejected, match="engine paused"):
        await gate.place_pending_order("XAUUSD", Side.BUY, OrderType.LIMIT, 0.1, 2395.0)
    assert order_service.pending_placed == []
