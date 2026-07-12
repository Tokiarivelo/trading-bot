from datetime import UTC, datetime

import pytest

from src.broker.domain.trading import OrderType, PendingOrder, Side, pending_order_triggered


def _order(side: Side, order_type: OrderType, price: float) -> PendingOrder:
    return PendingOrder(
        ticket=1,
        symbol="XAUUSD",
        side=side,
        order_type=order_type,
        volume=0.1,
        price=price,
        sl=None,
        tp=None,
        placed_time=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "side,order_type,price,bid,ask,expected",
    [
        # buy-limit: fills when ask drops to/through the (lower) trigger price
        (Side.BUY, OrderType.LIMIT, 100.0, 99.8, 100.0, True),
        (Side.BUY, OrderType.LIMIT, 100.0, 99.8, 100.1, False),
        # sell-limit: fills when bid rises to/through the (higher) trigger price
        (Side.SELL, OrderType.LIMIT, 100.0, 100.0, 100.2, True),
        (Side.SELL, OrderType.LIMIT, 100.0, 99.9, 100.1, False),
        # buy-stop: fills on a breakout up through the (higher) trigger price
        (Side.BUY, OrderType.STOP, 100.0, 99.8, 100.0, True),
        (Side.BUY, OrderType.STOP, 100.0, 99.6, 99.8, False),
        # sell-stop: fills on a breakout down through the (lower) trigger price
        (Side.SELL, OrderType.STOP, 100.0, 100.0, 100.2, True),
        (Side.SELL, OrderType.STOP, 100.0, 100.1, 100.3, False),
    ],
)
def test_pending_order_triggered(side, order_type, price, bid, ask, expected):
    order = _order(side, order_type, price)
    assert pending_order_triggered(order, bid, ask) is expected
