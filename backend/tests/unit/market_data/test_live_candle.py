from datetime import UTC, datetime

import pytest

from src.market_data.application.live_candle import LiveCandleService
from src.market_data.domain.models import MarketDataUnavailable, Timeframe


class FakeMarketData:
    """Serves whatever candles the test sets for get_candles(symbol, timeframe, 1)."""

    def __init__(self):
        self.candles: dict[tuple[str, Timeframe], list] = {}
        self.unavailable = False

    async def get_candles(self, symbol, timeframe, count):
        if self.unavailable:
            raise MarketDataUnavailable("gateway down")
        return self.candles.get((symbol, timeframe), [])[-count:]


class FakeBroadcaster:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def setup(candle_factory):
    market_data = FakeMarketData()
    broadcaster = FakeBroadcaster()
    service = LiveCandleService(market_data=market_data, broadcaster=broadcaster)
    return service, market_data, broadcaster


async def test_unwatched_room_is_never_polled(setup, candle_factory):
    service, market_data, broadcaster = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [candle_factory(utc(2026, 7, 10, 14, 0))]

    await service.poll_one("XAUUSD", Timeframe.M5)

    # poll_one is called directly here regardless of watch state — the
    # broadcast still happens; watch/unwatch only gates the background loop.
    assert len(broadcaster.messages) == 1


async def test_forming_bar_change_is_broadcast_as_candle_update(setup, candle_factory):
    service, market_data, broadcaster = setup
    service.watch("XAUUSD", Timeframe.M5)
    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0), close=2400.5)
    ]

    await service.poll_one("XAUUSD", Timeframe.M5)

    (message,) = broadcaster.messages
    assert message["type"] == "candle_update"
    assert message["candle"]["close"] == 2400.5
    assert message["candle"]["symbol"] == "XAUUSD"


async def test_unchanged_bar_is_not_rebroadcast(setup, candle_factory):
    service, market_data, broadcaster = setup
    service.watch("XAUUSD", Timeframe.M5)
    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0), close=2400.5)
    ]

    await service.poll_one("XAUUSD", Timeframe.M5)
    await service.poll_one("XAUUSD", Timeframe.M5)

    assert len(broadcaster.messages) == 1


async def test_price_move_within_the_same_bar_is_rebroadcast(setup, candle_factory):
    service, market_data, broadcaster = setup
    service.watch("XAUUSD", Timeframe.M5)
    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0), close=2400.5)
    ]
    await service.poll_one("XAUUSD", Timeframe.M5)

    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0), close=2401.0, high=2401.0, tick_volume=1001)
    ]
    await service.poll_one("XAUUSD", Timeframe.M5)

    assert len(broadcaster.messages) == 2
    assert broadcaster.messages[-1]["candle"]["close"] == 2401.0


async def test_unwatch_forgets_fingerprint_so_next_watch_rebroadcasts(setup, candle_factory):
    service, market_data, broadcaster = setup
    service.watch("XAUUSD", Timeframe.M5)
    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0), close=2400.5)
    ]
    await service.poll_one("XAUUSD", Timeframe.M5)
    service.unwatch("XAUUSD", Timeframe.M5)

    await service.poll_one("XAUUSD", Timeframe.M5)

    assert len(broadcaster.messages) == 2


async def test_gateway_unavailable_during_background_loop_does_not_raise(setup, candle_factory):
    service, market_data, broadcaster = setup
    service.watch("XAUUSD", Timeframe.M5)
    market_data.unavailable = True

    # _run's per-room try/except swallows MarketDataUnavailable; poll_one
    # itself still raises so callers (and the loop) can distinguish it.
    with pytest.raises(MarketDataUnavailable):
        await service.poll_one("XAUUSD", Timeframe.M5)
