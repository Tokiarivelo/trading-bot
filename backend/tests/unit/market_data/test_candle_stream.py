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


def test_poll_scheduling_targets_just_after_finest_boundary(setup):
    service, *_ = setup  # setup's fixture timeframes=[Timeframe.M5]
    delay = service._seconds_until_next_poll(utc(2026, 7, 10, 14, 3, 30))
    assert delay == pytest.approx(90 + 2.0)
    # Right after a boundary, wait for the next one — no tight loop.
    delay = service._seconds_until_next_poll(utc(2026, 7, 10, 14, 5, 0))
    assert delay >= 5.0


def test_poll_scheduling_uses_finest_configured_timeframe():
    service = CandleStreamService(
        market_data=FakeMarketData(),
        repository=FakeRepository(),
        event_bus=EventBus(),
        broadcaster=FakeBroadcaster(),
        symbols=["XAUUSD"],
        timeframes=[Timeframe.M1, Timeframe.M5, Timeframe.H1],
    )
    # M1 (60s) is the finest timeframe, so the next boundary is at 14:04:00.
    delay = service._seconds_until_next_poll(utc(2026, 7, 10, 14, 3, 30))
    assert delay == pytest.approx(30 + 2.0)


def test_watch_adds_ad_hoc_symbol_to_active_symbols(setup):
    service, *_ = setup
    assert service.active_symbols == ["XAUUSD"]

    service.watch("EURUSD")

    assert service.active_symbols == ["XAUUSD", "EURUSD"]


def test_watch_is_noop_for_already_configured_symbol(setup):
    service, *_ = setup

    service.watch("XAUUSD")

    assert service.active_symbols == ["XAUUSD"]


def test_unwatch_removes_symbol_once_last_watcher_leaves(setup):
    service, *_ = setup
    service.watch("EURUSD")  # e.g. two browser tabs charting the same symbol
    service.watch("EURUSD")

    service.unwatch("EURUSD")
    assert service.active_symbols == ["XAUUSD", "EURUSD"]

    service.unwatch("EURUSD")
    assert service.active_symbols == ["XAUUSD"]


def test_unwatch_never_removes_a_configured_symbol(setup):
    service, *_ = setup

    service.unwatch("XAUUSD")

    assert service.active_symbols == ["XAUUSD"]


async def test_ad_hoc_watched_symbol_is_polled_and_broadcast(setup, candle_factory):
    # The bug this guards against: a chart browsing a symbol outside
    # configs/app.yaml (e.g. via the symbol picker) must still receive live
    # candle_closed updates for as long as it's being watched, not just the
    # engine's configured universe.
    service, market_data, repository, broadcaster, events = setup
    service.watch("EURUSD")
    market_data.candles[("EURUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55), symbol="EURUSD")
    ]
    await service.poll_once(now=utc(2026, 7, 10, 14, 3))  # baseline

    market_data.candles[("EURUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55), symbol="EURUSD"),
        candle_factory(utc(2026, 7, 10, 14, 0), symbol="EURUSD", close=1.09),
    ]
    emitted = await service.poll_once(now=utc(2026, 7, 10, 14, 5, 2))

    assert [c.time for c in emitted] == [utc(2026, 7, 10, 14, 0)]
    assert any(m["candle"]["symbol"] == "EURUSD" for m in broadcaster.messages)


async def test_multiple_closed_bars_since_last_poll_are_all_emitted(setup, candle_factory):
    # If a poll is delayed, more than one bar of a fine timeframe (e.g. M1)
    # can close in between — every one of them must still be emitted, not
    # just the newest.
    service, market_data, repository, broadcaster, events = setup
    market_data.candles[("XAUUSD", Timeframe.M5)] = [candle_factory(utc(2026, 7, 10, 13, 55))]
    await service.poll_once(now=utc(2026, 7, 10, 14, 3))  # baseline

    market_data.candles[("XAUUSD", Timeframe.M5)] = [
        candle_factory(utc(2026, 7, 10, 13, 55)),
        candle_factory(utc(2026, 7, 10, 14, 0), close=2405.0),
        candle_factory(utc(2026, 7, 10, 14, 5), close=2410.0),
    ]
    emitted = await service.poll_once(now=utc(2026, 7, 10, 14, 10, 2))

    assert [c.time for c in emitted] == [utc(2026, 7, 10, 14, 0), utc(2026, 7, 10, 14, 5)]
    assert [e.occurred_at for e in events] and len(events) == 2
    assert len(broadcaster.messages) == 2
