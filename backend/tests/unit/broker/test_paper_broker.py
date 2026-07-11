from datetime import UTC, datetime

import pytest

from src.broker.adapters.paper import PaperBroker
from src.broker.domain.trading import OrderRejected, OrderRequest, Side
from src.market_data.domain.models import SymbolInfo

XAUUSD = SymbolInfo(
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


class FakeMarketData:
    def __init__(self, info: SymbolInfo = XAUUSD) -> None:
        self.info = info

    async def get_candles(self, symbol, timeframe, count):
        raise NotImplementedError

    async def get_tick(self, symbol):
        raise NotImplementedError

    async def get_symbol_info(self, symbol):
        return self.info


@pytest.fixture
def broker() -> PaperBroker:
    return PaperBroker(FakeMarketData())


async def test_buy_fills_at_ask(broker):
    result = await broker.open_position(
        OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=0.1, sl=2390.0, tp=2420.0)
    )
    assert result.price == 2400.35
    assert result.spread_points == 25
    assert result.profit is None
    assert result.ticket > 0


async def test_sell_fills_at_bid(broker):
    result = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.SELL, volume=0.1))
    assert result.price == 2400.10


async def test_close_long_realizes_profit_at_bid(broker):
    opened = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=1.0))
    closed = await broker.close_position(opened.ticket)
    # profit = (bid - open_price_ask) * contract_size * volume
    expected = (2400.10 - 2400.35) * 100.0 * 1.0
    assert closed.price == 2400.10
    assert closed.profit == pytest.approx(expected)


async def test_close_short_realizes_profit_at_ask(broker):
    opened = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.SELL, volume=1.0))
    closed = await broker.close_position(opened.ticket)
    # short: opened at bid, closed at ask — a wider spread costs the short too
    expected = (2400.35 - 2400.10) * -1.0 * 100.0 * 1.0
    assert closed.price == 2400.35
    assert closed.profit == pytest.approx(expected)


async def test_close_unknown_ticket_raises(broker):
    with pytest.raises(OrderRejected):
        await broker.close_position(999)


async def test_partial_close_leaves_remaining_position_open(broker):
    opened = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=1.0))
    await broker.close_position(opened.ticket, volume=0.4)

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].volume == pytest.approx(0.6)


async def test_full_close_removes_position(broker):
    opened = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=1.0))
    await broker.close_position(opened.ticket)
    assert await broker.get_positions() == []


async def test_modify_updates_sl_tp(broker):
    opened = await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=0.1))
    await broker.modify_position(opened.ticket, sl=2395.0, tp=2415.0)

    (position,) = await broker.get_positions()
    assert position.sl == 2395.0
    assert position.tp == 2415.0


async def test_modify_unknown_ticket_raises(broker):
    with pytest.raises(OrderRejected):
        await broker.modify_position(999, sl=1.0, tp=2.0)


async def test_get_positions_filters_by_symbol(broker):
    await broker.open_position(OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=0.1))
    assert len(await broker.get_positions(symbol="XAUUSD")) == 1
    assert await broker.get_positions(symbol="BTCUSD") == []


async def test_close_at_price_long_uses_explicit_price(broker):
    opened = await broker.open_position(
        OrderRequest(symbol="XAUUSD", side=Side.BUY, volume=1.0, sl=2390.0)
    )
    at = datetime(2025, 1, 1, tzinfo=UTC)
    closed = await broker.close_at_price(opened.ticket, 2390.0, at)

    expected = (2390.0 - 2400.35) * 100.0 * 1.0
    assert closed.price == 2390.0
    assert closed.time == at
    assert closed.profit == pytest.approx(expected)
    assert await broker.get_positions() == []


async def test_close_at_price_short_uses_explicit_price(broker):
    opened = await broker.open_position(
        OrderRequest(symbol="XAUUSD", side=Side.SELL, volume=1.0, tp=2380.0)
    )
    closed = await broker.close_at_price(opened.ticket, 2380.0, datetime(2025, 1, 1, tzinfo=UTC))

    expected = (2380.0 - 2400.10) * -1.0 * 100.0 * 1.0
    assert closed.price == 2380.0
    assert closed.profit == pytest.approx(expected)


async def test_close_at_price_unknown_ticket_raises(broker):
    with pytest.raises(OrderRejected):
        await broker.close_at_price(999, 2400.0, datetime(2025, 1, 1, tzinfo=UTC))
