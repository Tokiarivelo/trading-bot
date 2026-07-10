from src.shared.events.bus import EventBus
from src.shared.events.definitions import CandleClosed, PositionClosed


async def test_publish_reaches_all_subscribers():
    bus = EventBus()
    received: list[CandleClosed] = []

    async def handler_a(event):
        received.append(event)

    async def handler_b(event):
        received.append(event)

    bus.subscribe(CandleClosed, handler_a)
    bus.subscribe(CandleClosed, handler_b)

    event = CandleClosed(symbol="XAUUSD", timeframe="M5")
    await bus.publish(event)

    assert received == [event, event]


async def test_publish_only_reaches_matching_event_type():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(PositionClosed, handler)
    await bus.publish(CandleClosed(symbol="XAUUSD", timeframe="M5"))

    assert received == []


async def test_failing_handler_does_not_break_others():
    bus = EventBus()
    received = []

    async def bad_handler(event):
        raise RuntimeError("boom")

    async def good_handler(event):
        received.append(event)

    bus.subscribe(CandleClosed, bad_handler)
    bus.subscribe(CandleClosed, good_handler)

    event = CandleClosed(symbol="BTCUSD", timeframe="M5")
    await bus.publish(event)

    assert received == [event]
