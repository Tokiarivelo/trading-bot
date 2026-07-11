from datetime import UTC, datetime

from src.broker.domain.trading import Position, Side
from src.engine.application.position_manager import PositionManager
from src.market_data.domain.models import SymbolInfo

INFO = SymbolInfo(
    symbol="XAUUSD",
    bid=2410.00,
    ask=2410.20,
    spread_points=20,
    point=0.01,
    digits=2,
    stops_level=10,
    contract_size=100.0,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
)


def _position(**overrides) -> Position:
    defaults = dict(
        ticket=1,
        symbol="XAUUSD",
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=2390.0,
        tp=2420.0,
        open_time=datetime.now(UTC),
        profit=0.0,
        comment="",
    )
    defaults.update(overrides)
    return Position(**defaults)


class FakeOrderService:
    def __init__(self, positions: list[Position]) -> None:
        self._positions = positions
        self.modified: list[tuple[int, float | None, float | None]] = []
        self.closed: list[int] = []

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        return list(self._positions)

    async def modify_position(self, ticket: int, sl, tp) -> None:
        self.modified.append((ticket, sl, tp))

    async def close_position(self, ticket: int, volume=None):
        self.closed.append(ticket)
        self._positions = [p for p in self._positions if p.ticket != ticket]


class FakeMarketData:
    def __init__(self, info: SymbolInfo = INFO) -> None:
        self.info = info

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return self.info


async def test_moves_sl_to_breakeven_once_risk_is_covered():
    # risk = open(2400) - sl(2390) = 10; bid(2410) - open(2400) = 10 >= risk
    position = _position(open_price=2400.0, sl=2390.0)
    order_service = FakeOrderService([position])
    manager = PositionManager(order_service, FakeMarketData())

    await manager.on_candle_closed("XAUUSD")

    assert order_service.modified == [(1, 2400.0, 2420.0)]
    assert order_service.closed == []


async def test_does_not_move_sl_before_risk_is_covered():
    # risk = 2400-2380=20; progress = bid(2410)-2400=10 < risk
    position = _position(open_price=2400.0, sl=2380.0)
    order_service = FakeOrderService([position])
    manager = PositionManager(order_service, FakeMarketData())

    await manager.on_candle_closed("XAUUSD")

    assert order_service.modified == []


async def test_time_stop_closes_position_without_progress():
    # sell position marked at ask(2410.20) > open(2400) -> losing, no progress
    position = _position(side=Side.SELL, open_price=2400.0, sl=2420.0)
    order_service = FakeOrderService([position])
    manager = PositionManager(order_service, FakeMarketData(), time_stop_candles=2)

    await manager.on_candle_closed("XAUUSD")
    await manager.on_candle_closed("XAUUSD")

    assert order_service.closed == [1]


async def test_no_sl_means_position_is_left_alone():
    position = _position(sl=None)
    order_service = FakeOrderService([position])
    manager = PositionManager(order_service, FakeMarketData(), time_stop_candles=1)

    await manager.on_candle_closed("XAUUSD")

    assert order_service.modified == []
    assert order_service.closed == []
