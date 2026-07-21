from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.journal.adapters.repository import JournalRepository
from src.journal.application.trade_journal import TradeJournalService
from src.journal.domain.models import CandleSnapshot, MarketSnapshot
from src.shared.db.base import Base
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened, TenTradesCompleted


class FakeMarketContext:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.snapshot = MarketSnapshot(
            m5=(
                CandleSnapshot(
                    time=datetime(2026, 7, 10, 13, 55, tzinfo=UTC),
                    open=1,
                    high=2,
                    low=0.5,
                    close=1.5,
                    tick_volume=100,
                ),
            ),
            h1=(),
        )

    async def capture(self, symbol):
        self.calls.append(symbol)
        return self.snapshot


@pytest.fixture
def repository(tmp_path) -> JournalRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return JournalRepository(sessionmaker(bind=engine, expire_on_commit=False))


@pytest.fixture
def market_context() -> FakeMarketContext:
    return FakeMarketContext()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def service(repository, market_context, event_bus) -> TradeJournalService:
    return TradeJournalService(
        repository=repository,
        market_context=market_context,
        event_bus=event_bus,
        review_every_n_trades=3,
    )


def opened_event(
    position_id="1", symbol="XAUUSD", skill="normal/xauusd/breakout_v1"
) -> PositionOpened:
    return PositionOpened(
        symbol=symbol,
        position_id=position_id,
        side="buy",
        volume=0.1,
        price=2400.35,
        sl=2390.0,
        tp=2420.0,
        spread_points=25,
        comment="",
        skill=skill,
    )


def closed_event(position_id="1", symbol="XAUUSD", profit=9.65, occurred_at=None) -> PositionClosed:
    kwargs = {"occurred_at": occurred_at} if occurred_at else {}
    return PositionClosed(
        symbol=symbol, position_id=position_id, close_price=2410.0, profit=profit, **kwargs
    )


async def test_on_position_opened_journals_entry_with_snapshot(service, repository, market_context):
    await service.on_position_opened(opened_event())

    record = repository.get("1")
    assert record is not None
    assert record.symbol == "XAUUSD"
    assert record.open_price == 2400.35
    assert record.is_open is True
    assert record.m5_entry_snapshot == market_context.snapshot.m5
    assert market_context.calls == ["XAUUSD"]


async def test_on_position_closed_updates_existing_record(service, repository):
    await service.on_position_opened(opened_event())
    await service.on_position_closed(closed_event())

    record = repository.get("1")
    assert record.is_open is False
    assert record.close_price == 2410.0
    assert record.profit == 9.65
    assert record.m5_exit_snapshot != ()


async def test_on_position_closed_without_matching_open_is_ignored(service, repository):
    await service.on_position_closed(closed_event(position_id="missing"))
    assert repository.get("missing") is None


async def test_ten_trade_review_fires_after_n_closed_trades(service, event_bus):
    published = []

    async def record(event):
        published.append(event)

    event_bus.subscribe(TenTradesCompleted, record)

    for i in range(3):
        await service.on_position_opened(opened_event(position_id=str(i)))
        await service.on_position_closed(
            closed_event(
                position_id=str(i),
                profit=float(i),
                occurred_at=datetime(2026, 7, 10, 15, i, tzinfo=UTC),
            )
        )

    assert len(published) == 1
    assert isinstance(published[0], TenTradesCompleted)
    assert published[0].symbol == "XAUUSD"
    assert published[0].skill == "normal/xauusd/breakout_v1"
    assert published[0].trade_ids == ("0", "1", "2")


async def test_no_review_event_before_threshold(service, event_bus):
    published = []

    async def record(event):
        published.append(event)

    event_bus.subscribe(TenTradesCompleted, record)

    await service.on_position_opened(opened_event(position_id="1"))
    await service.on_position_closed(closed_event(position_id="1"))

    assert published == []


async def test_manual_trade_with_no_skill_never_triggers_review(service, event_bus):
    published = []

    async def record(event):
        published.append(event)

    event_bus.subscribe(TenTradesCompleted, record)

    for i in range(3):
        await service.on_position_opened(opened_event(position_id=str(i), skill=None))
        await service.on_position_closed(
            closed_event(position_id=str(i), occurred_at=datetime(2026, 7, 10, 15, i, tzinfo=UTC))
        )

    assert published == []


async def test_two_bots_on_one_symbol_are_reviewed_on_independent_cadences(service, event_bus):
    published = []

    async def record(event):
        published.append(event)

    event_bus.subscribe(TenTradesCompleted, record)

    # Bot A's 3rd closed trade should trigger a review scoped to bot A only,
    # even though bot B has also been trading the same symbol concurrently.
    for i in range(2):
        await service.on_position_opened(opened_event(position_id=f"a{i}", skill="normal/xauusd/a"))
        await service.on_position_closed(
            closed_event(position_id=f"a{i}", occurred_at=datetime(2026, 7, 10, 15, i, tzinfo=UTC))
        )
    await service.on_position_opened(opened_event(position_id="b0", skill="normal/xauusd/b"))
    await service.on_position_closed(
        closed_event(position_id="b0", occurred_at=datetime(2026, 7, 10, 15, 10, tzinfo=UTC))
    )
    await service.on_position_opened(opened_event(position_id="a2", skill="normal/xauusd/a"))
    await service.on_position_closed(
        closed_event(position_id="a2", occurred_at=datetime(2026, 7, 10, 15, 11, tzinfo=UTC))
    )

    assert len(published) == 1
    assert published[0].skill == "normal/xauusd/a"
    assert published[0].trade_ids == ("a0", "a1", "a2")


async def test_get_markers_and_get_last_n_proxy_repository(service):
    await service.on_position_opened(opened_event())
    await service.on_position_closed(closed_event())

    markers = await service.get_markers("XAUUSD")
    assert len(markers) == 1

    last = await service.get_last_n("XAUUSD", 5)
    assert len(last) == 1


async def test_get_markers_skill_filter_proxies_through(service):
    await service.on_position_opened(opened_event(position_id="a", skill="normal/xauusd/a"))
    await service.on_position_opened(opened_event(position_id="b", skill="normal/xauusd/b"))

    markers = await service.get_markers("XAUUSD", skill="normal/xauusd/a")

    assert [m.id for m in markers] == ["a"]
