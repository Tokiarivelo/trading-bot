from datetime import UTC, datetime

from src.broker.domain.trading import ExecutionResult, OrderType, PendingOrder, Position, Side
from src.engine.application.position_manager import PositionManager
from src.engine.application.risk_manager import RiskManager
from src.engine.domain.models import RiskCaps
from src.market_data.domain.models import SymbolInfo

CAPS = RiskCaps(
    risk_per_trade_pct=0.5,
    daily_loss_limit_pct=2.0,
    max_open_positions=5,
    max_trades_per_day=8,
    consecutive_loss_pause=3,
)

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
    def __init__(
        self,
        positions: list[Position],
        pending: list[PendingOrder] | None = None,
        simulates_pending_fills: bool = True,
    ) -> None:
        self._positions = positions
        self._pending = pending or []
        self._simulates_pending_fills = simulates_pending_fills
        self.modified: list[tuple[int, float | None, float | None]] = []
        self.closed: list[int] = []
        self.opened: list = []
        self.pending_cancelled: list[int] = []

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        return list(self._positions)

    async def modify_position(self, ticket: int, sl, tp) -> None:
        self.modified.append((ticket, sl, tp))

    async def close_position(self, ticket: int, volume=None):
        self.closed.append(ticket)
        self._positions = [p for p in self._positions if p.ticket != ticket]

    async def get_pending_orders(self, symbol: str | None = None) -> list[PendingOrder]:
        return [p for p in self._pending if symbol is None or p.symbol == symbol]

    @property
    def simulates_pending_fills(self) -> bool:
        return self._simulates_pending_fills

    async def open_position(self, symbol, side, volume, sl=None, tp=None, comment=""):
        self.opened.append((symbol, side, volume, sl, tp, comment))
        ticket = 100 + len(self.opened)
        new_position = Position(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=volume,
            open_price=INFO.ask if side is Side.BUY else INFO.bid,
            sl=sl,
            tp=tp,
            open_time=datetime.now(UTC),
            profit=0.0,
        )
        self._positions.append(new_position)
        return ExecutionResult(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=volume,
            price=new_position.open_price,
            sl=sl,
            tp=tp,
            time=datetime.now(UTC),
            spread_points=20,
            comment=comment,
        )

    async def cancel_pending_order(self, ticket: int) -> None:
        self.pending_cancelled.append(ticket)
        self._pending = [p for p in self._pending if p.ticket != ticket]


class FakeReconciliation:
    def __init__(self) -> None:
        self.vanished_calls: list[tuple[str, set[int]]] = []
        self.pending_fill_calls: list[tuple[str, int, Side, float]] = []
        self.fill_result = True

    async def reconcile_vanished(self, symbol: str, tickets: set[int]) -> None:
        self.vanished_calls.append((symbol, tickets))

    async def reconcile_pending_fill(
        self, symbol: str, ticket: int, side: Side, volume: float
    ) -> bool:
        self.pending_fill_calls.append((symbol, ticket, side, volume))
        return self.fill_result


def _pending_order(**overrides) -> PendingOrder:
    defaults = dict(
        ticket=50,
        symbol="XAUUSD",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        volume=0.1,
        price=2405.0,
        sl=2395.0,
        tp=2420.0,
        placed_time=datetime.now(UTC),
        comment="",
    )
    defaults.update(overrides)
    return PendingOrder(**defaults)


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


async def test_paper_pending_order_fills_when_triggered_and_gate_approves():
    # ask=2410.20 <= price(2415.0) -> buy-limit triggers
    order_service = FakeOrderService([], pending=[_pending_order(price=2415.0)])
    risk_manager = RiskManager(caps=CAPS, timezone="UTC")
    manager = PositionManager(order_service, FakeMarketData(), risk_manager=risk_manager)

    await manager.on_candle_closed("XAUUSD")

    assert len(order_service.opened) == 1
    assert order_service.pending_cancelled == [50]
    assert risk_manager.status.trades_today == 1


async def test_paper_pending_order_stays_resting_when_not_triggered():
    # ask=2410.20 > price(2405.0) -> buy-limit not yet triggered
    order_service = FakeOrderService([], pending=[_pending_order(price=2405.0)])
    risk_manager = RiskManager(caps=CAPS, timezone="UTC")
    manager = PositionManager(order_service, FakeMarketData(), risk_manager=risk_manager)

    await manager.on_candle_closed("XAUUSD")

    assert order_service.opened == []
    assert order_service.pending_cancelled == []


async def test_paper_pending_order_left_pending_when_risk_cap_blocks():
    blocked_caps = RiskCaps(
        risk_per_trade_pct=0.5,
        daily_loss_limit_pct=2.0,
        max_open_positions=0,
        max_trades_per_day=8,
        consecutive_loss_pause=3,
    )
    order_service = FakeOrderService([], pending=[_pending_order(price=2415.0)])
    risk_manager = RiskManager(caps=blocked_caps, timezone="UTC")
    manager = PositionManager(order_service, FakeMarketData(), risk_manager=risk_manager)

    await manager.on_candle_closed("XAUUSD")

    assert order_service.opened == []
    assert order_service.pending_cancelled == []


async def test_live_mode_reconciles_a_pending_order_that_vanished():
    pending_order = _pending_order(ticket=50)
    order_service = FakeOrderService([], pending=[pending_order], simulates_pending_fills=False)
    risk_manager = RiskManager(caps=CAPS, timezone="UTC")
    reconciliation = FakeReconciliation()
    manager = PositionManager(
        order_service, FakeMarketData(), reconciliation=reconciliation, risk_manager=risk_manager
    )

    await manager.on_candle_closed("XAUUSD")  # seed: ticket 50 seen resting
    order_service._pending = []  # MT5 triggered it server-side
    await manager.on_candle_closed("XAUUSD")

    assert reconciliation.pending_fill_calls == [("XAUUSD", 50, Side.BUY, 0.1)]
    assert risk_manager.status.trades_today == 1


async def test_live_mode_does_not_record_trade_when_no_match_found():
    pending_order = _pending_order(ticket=50)
    order_service = FakeOrderService([], pending=[pending_order], simulates_pending_fills=False)
    risk_manager = RiskManager(caps=CAPS, timezone="UTC")
    reconciliation = FakeReconciliation()
    reconciliation.fill_result = False
    manager = PositionManager(
        order_service, FakeMarketData(), reconciliation=reconciliation, risk_manager=risk_manager
    )

    await manager.on_candle_closed("XAUUSD")
    order_service._pending = []
    await manager.on_candle_closed("XAUUSD")

    assert reconciliation.pending_fill_calls == [("XAUUSD", 50, Side.BUY, 0.1)]
    assert risk_manager.status.trades_today == 0


async def test_risk_manager_none_skips_pending_order_handling():
    order_service = FakeOrderService([], pending=[_pending_order(price=2415.0)])
    manager = PositionManager(order_service, FakeMarketData())

    await manager.on_candle_closed("XAUUSD")

    assert order_service.opened == []
    assert order_service.pending_cancelled == []
