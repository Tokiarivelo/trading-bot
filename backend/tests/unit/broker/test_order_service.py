from datetime import UTC, datetime

import pytest

from src.broker.application.order_service import OrderService
from src.broker.application.spread_gate import SpreadGate
from src.broker.domain.symbol_config import SymbolTradingConfig
from src.broker.domain.trading import (
    ExecutionResult,
    OrderRejected,
    OrderType,
    PendingOrder,
    Position,
    Side,
)
from src.market_data.domain.models import SymbolInfo
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened

XAUUSD_INFO = SymbolInfo(
    symbol="XAUUSD",
    bid=2400.10,
    ask=2400.35,
    spread_points=25,
    point=0.01,
    digits=2,
    stops_level=10,
    contract_size=100.0,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
)
CONFIG = SymbolTradingConfig(
    symbol="XAUUSD",
    max_spread_points=35,
    min_rr=1.5,
    contract_size=100,
    point=0.01,
    digits=2,
    stops_level=0,
    volume_min=0.01,
    volume_max=50,
    volume_step=0.01,
)


class FakeMarketData:
    def __init__(self, info: SymbolInfo = XAUUSD_INFO) -> None:
        self.info = info

    async def get_candles(self, symbol, timeframe, count):
        raise NotImplementedError

    async def get_tick(self, symbol):
        raise NotImplementedError

    async def get_symbol_info(self, symbol):
        return self.info


class FakeBroker:
    def __init__(self, simulates_pending_fills: bool = True) -> None:
        self.opened: list = []
        self.closed: list = []
        self.modified: list = []
        self.pending_placed: list = []
        self.pending_cancelled: list = []
        self.pending_modified: list = []
        self._simulates_pending_fills = simulates_pending_fills

    async def open_position(self, order):
        self.opened.append(order)
        return ExecutionResult(
            ticket=1,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            price=2400.35,
            sl=order.sl,
            tp=order.tp,
            time=datetime.now(UTC),
            spread_points=25,
            comment=order.comment,
        )

    async def close_position(self, ticket, volume=None):
        self.closed.append((ticket, volume))
        return ExecutionResult(
            ticket=ticket,
            symbol="XAUUSD",
            side=Side.BUY,
            volume=volume or 0.1,
            price=2400.10,
            sl=None,
            tp=None,
            time=datetime.now(UTC),
            spread_points=25,
            profit=-25.0,
        )

    async def modify_position(self, ticket, sl, tp):
        self.modified.append((ticket, sl, tp))

    async def get_positions(self, symbol=None):
        return [
            Position(
                ticket=1,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.1,
                open_price=2400.35,
                sl=None,
                tp=None,
                open_time=datetime.now(UTC),
                profit=0.0,
            )
        ]

    async def place_pending_order(self, order):
        self.pending_placed.append(order)
        return PendingOrder(
            ticket=2,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            volume=order.volume,
            price=order.price,
            sl=order.sl,
            tp=order.tp,
            placed_time=datetime.now(UTC),
            comment=order.comment,
        )

    async def cancel_pending_order(self, ticket):
        self.pending_cancelled.append(ticket)

    async def modify_pending_order(self, ticket, price, sl, tp):
        self.pending_modified.append((ticket, price, sl, tp))

    async def get_pending_orders(self, symbol=None):
        return []

    @property
    def simulates_pending_fills(self):
        return self._simulates_pending_fills


def make_service(broker=None):
    broker = broker or FakeBroker()
    event_bus = EventBus()
    published = []

    async def _record(event):
        published.append(event)

    event_bus.subscribe(PositionOpened, _record)
    event_bus.subscribe(PositionClosed, _record)
    service = OrderService(
        broker=broker,
        market_data=FakeMarketData(),
        spread_gate=SpreadGate({"XAUUSD": CONFIG}),
        event_bus=event_bus,
    )
    return service, broker, event_bus, published


async def test_open_position_fills_and_publishes_event():
    service, broker, _, published = make_service()
    result = await service.open_position(
        "XAUUSD", Side.BUY, 0.1, sl=2390.0, tp=2420.0, comment="test"
    )
    assert result.ticket == 1
    assert len(broker.opened) == 1
    assert len(published) == 1
    event = published[0]
    assert isinstance(event, PositionOpened)
    assert event.symbol == "XAUUSD"
    assert event.side == "buy"
    assert event.price == 2400.35
    assert event.spread_points == 25


async def test_spread_veto_blocks_order_and_publishes_nothing():
    service, broker, _, published = make_service()
    with pytest.raises(OrderRejected):
        await service.open_position("XAUUSD", Side.BUY, 0.1, sl=2399.0, tp=2400.5)
    assert broker.opened == []
    assert published == []


async def test_open_position_without_sl_tp_skips_rr_check():
    # sl/tp are optional (F-manual-trading) — omitting either one means
    # there's no RR to evaluate, so the RR gate can't block it.
    service, broker, _, published = make_service()
    result = await service.open_position("XAUUSD", Side.BUY, 0.1)
    assert result.ticket == 1
    assert len(broker.opened) == 1
    assert len(published) == 1


async def test_close_position_publishes_event_with_profit():
    service, broker, _, published = make_service()
    result = await service.close_position(1, volume=0.1)
    assert result.profit == -25.0
    assert broker.closed == [(1, 0.1)]
    (event,) = published
    assert isinstance(event, PositionClosed)
    assert event.profit == -25.0
    assert event.close_price == 2400.10


async def test_modify_position_delegates_to_broker():
    service, broker, _, _ = make_service()
    await service.modify_position(1, sl=2395.0, tp=2415.0)
    assert broker.modified == [(1, 2395.0, 2415.0)]


async def test_get_positions_delegates_to_broker():
    service, _, _, _ = make_service()
    positions = await service.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "XAUUSD"


async def test_place_pending_order_delegates_to_broker():
    service, broker, _, _ = make_service()
    result = await service.place_pending_order(
        "XAUUSD", Side.BUY, OrderType.LIMIT, 0.1, 2395.0, sl=2390.0, tp=2415.0
    )
    assert result.ticket == 2
    assert len(broker.pending_placed) == 1
    assert broker.pending_placed[0].price == 2395.0


async def test_cancel_pending_order_delegates_to_broker():
    service, broker, _, _ = make_service()
    await service.cancel_pending_order(2)
    assert broker.pending_cancelled == [2]


async def test_modify_pending_order_delegates_to_broker():
    service, broker, _, _ = make_service()
    await service.modify_pending_order(2, price=2394.0, sl=None, tp=2415.0)
    assert broker.pending_modified == [(2, 2394.0, None, 2415.0)]


async def test_simulates_pending_fills_passes_through_broker_flag():
    service, _, _, _ = make_service(FakeBroker(simulates_pending_fills=False))
    assert service.simulates_pending_fills is False
