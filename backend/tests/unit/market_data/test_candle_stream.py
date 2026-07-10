from datetime import UTC, datetime

import pytest

from src.market_data.application.candle_stream import CandleStreamService
from src.market_data.domain.models import Timeframe
from src.shared.events.bus import EventBus
from src.shared.events.definitions import CandleClosed


class FakeMarketData:
    """Serves whatever candles the test sets; last one may be forming."""

    def __init__(self):
        self.candles: dict[tuple[str, Timeframe], list] = {}

    async def get_candles(self, symbol, timeframe, count):
        return self.candles.get((symbol, timeframe), [])


class FakeRepository:
    def __init__(self):
        self.stored = []

    def upsert_many(self, candles):
        self.stored.extend(candles)
        return len(list(candles))


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
    repository = FakeRepository()
    broadcaster = FakeBroadcaster()
    bus = EventBus()
    events: list[CandleClosed] = []

    async def capture(event):
        events.append(event)

    bus.subscribe(CandleClosed, capture)
    service = CandleStreamService(
        market_data=market_data,
        repository=repository,
        event_bus=bus,
        broadcaster=broadcaster,
        symbols=["XAUUSD"],
        timeframes=[Timeframe.M5],
    )
    return service, market_data, repository, broadcaster, events


async def test_first_poll_baselines_without_emitting(setup, candle_factory):
    service, market_data, repository, broadcaster, events = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55)),
        candle_factory(utc(2026, 7, 10, 14, 0)),  # forming at 14:03
    ]

    emitted = await service.poll_once(now=utc(2026, 7, 10, 14, 3))

    assert emitted == []
    assert events == []
    # ...but closed history is persisted right away.
    assert [c.time for c in repository.stored] == [utc(2026, 7, 10, 13, 55)]


async def test_new_closed_bar_is_emitted_persisted_broadcast(setup, candle_factory):
    service, market_data, repository, broadcaster, events = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [candle_factory(utc(2026, 7, 10, 13, 55))]
    await service.poll_once(now=utc(2026, 7, 10, 14, 3))  # baseline

    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55)),
        candle_factory(utc(2026, 7, 10, 14, 0), close=2405.0),
    ]
    emitted = await service.poll_once(now=utc(2026, 7, 10, 14, 5, 2))

    assert [c.time for c in emitted] == [utc(2026, 7, 10, 14, 0)]
    assert events == [
        CandleClosed(symbol="XAUUSD", timeframe="M5", occurred_at=events[0].occurred_at)
    ]
    (message,) = broadcaster.messages
    assert message["type"] == "candle_closed"
    assert message["candle"]["close"] == 2405.0
    assert message["candle"]["time"] == int(utc(2026, 7, 10, 14, 0).timestamp())


async def test_same_bar_is_not_emitted_twice(setup, candle_factory):
    service, market_data, repository, broadcaster, events = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [candle_factory(utc(2026, 7, 10, 13, 55))]
    await service.poll_once(now=utc(2026, 7, 10, 14, 3))  # baseline

    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 14, 0)),
    ]
    await service.poll_once(now=utc(2026, 7, 10, 14, 5, 2))
    again = await service.poll_once(now=utc(2026, 7, 10, 14, 6))

    assert again == []
    assert len(events) == 1


async def test_forming_bar_is_never_emitted(setup, candle_factory):
    service, market_data, repository, broadcaster, events = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [candle_factory(utc(2026, 7, 10, 13, 55))]
    await service.poll_once(now=utc(2026, 7, 10, 14, 3))  # baseline

    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55)),
        candle_factory(utc(2026, 7, 10, 14, 0)),  # still forming at 14:04
    ]
    emitted = await service.poll_once(now=utc(2026, 7, 10, 14, 4))

    assert emitted == []
    assert all(c.time != utc(2026, 7, 10, 14, 0) for c in repository.stored)


def test_poll_scheduling_targets_just_after_m5_boundary():
    delay = CandleStreamService._seconds_until_next_poll(utc(2026, 7, 10, 14, 3, 30))
    assert delay == pytest.approx(90 + 2.0)
    # Right after a boundary, wait for the next one — no tight loop.
    delay = CandleStreamService._seconds_until_next_poll(utc(2026, 7, 10, 14, 5, 0))
    assert delay >= 5.0
