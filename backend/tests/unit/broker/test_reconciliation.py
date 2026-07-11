from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.broker.application.reconciliation import ReconciliationService
from src.broker.domain.trading import ClosedPositionInfo, Position, Side
from src.journal.adapters.repository import JournalRepository
from src.journal.application.trade_journal import TradeJournalService
from src.journal.domain.models import MarketSnapshot
from src.shared.db.base import Base
from src.shared.events.bus import EventBus
from src.shared.events.definitions import PositionClosed, PositionOpened


class FakeMarketContext:
    async def capture(self, symbol):
        return MarketSnapshot(m5=(), h1=())


class FakeBroker:
    def __init__(self, open_positions: list[Position], close_info: dict[int, ClosedPositionInfo]):
        self._open_positions = open_positions
        self._close_info = close_info

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        if symbol is None:
            return list(self._open_positions)
        return [p for p in self._open_positions if p.symbol == symbol]

    async def get_close_info(self, ticket: int) -> ClosedPositionInfo | None:
        return self._close_info.get(ticket)


@pytest.fixture
def journal(tmp_path) -> TradeJournalService:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    repository = JournalRepository(sessionmaker(bind=engine, expire_on_commit=False))
    return TradeJournalService(
        repository=repository, market_context=FakeMarketContext(), event_bus=EventBus()
    )


def _open_position(ticket=1, symbol="XAUUSD") -> Position:
    return Position(
        ticket=ticket,
        symbol=symbol,
        side=Side.BUY,
        volume=0.1,
        open_price=2400.0,
        sl=2390.0,
        tp=2420.0,
        open_time=datetime.now(UTC),
        profit=0.0,
    )


async def test_reconcile_all_closes_journaled_trade_the_broker_no_longer_shows(journal):
    await journal.on_position_opened(
        PositionOpened(
            symbol="XAUUSD",
            position_id="1",
            side="buy",
            volume=0.1,
            price=2400.0,
            sl=2390.0,
            tp=2420.0,
            spread_points=25,
        )
    )
    close_info = ClosedPositionInfo(
        symbol="XAUUSD", price=2390.0, time=datetime.now(UTC), profit=-10.0
    )
    broker = FakeBroker(open_positions=[], close_info={1: close_info})
    event_bus = EventBus()
    published: list[PositionClosed] = []

    async def on_closed(event: PositionClosed) -> None:
        published.append(event)

    event_bus.subscribe(PositionClosed, on_closed)
    reconciliation = ReconciliationService(broker=broker, journal=journal, event_bus=event_bus)

    await reconciliation.reconcile_all()

    assert len(published) == 1
    assert published[0].position_id == "1"
    assert published[0].profit == -10.0


async def test_reconcile_all_skips_trades_still_open_at_the_broker(journal):
    await journal.on_position_opened(
        PositionOpened(
            symbol="XAUUSD",
            position_id="1",
            side="buy",
            volume=0.1,
            price=2400.0,
            sl=2390.0,
            tp=2420.0,
            spread_points=25,
        )
    )
    broker = FakeBroker(open_positions=[_open_position(ticket=1)], close_info={})
    event_bus = EventBus()
    published: list[PositionClosed] = []

    async def on_closed(event: PositionClosed) -> None:
        published.append(event)

    event_bus.subscribe(PositionClosed, on_closed)
    reconciliation = ReconciliationService(broker=broker, journal=journal, event_bus=event_bus)

    await reconciliation.reconcile_all()

    assert published == []


async def test_reconcile_vanished_logs_and_skips_when_no_close_history(journal):
    broker = FakeBroker(open_positions=[], close_info={})
    event_bus = EventBus()
    published: list[PositionClosed] = []

    async def on_closed(event: PositionClosed) -> None:
        published.append(event)

    event_bus.subscribe(PositionClosed, on_closed)
    reconciliation = ReconciliationService(broker=broker, journal=journal, event_bus=event_bus)

    await reconciliation.reconcile_vanished("XAUUSD", {99})

    assert published == []


async def test_reconcile_vanished_publishes_position_closed(journal):
    close_info = ClosedPositionInfo(
        symbol="XAUUSD", price=2405.0, time=datetime.now(UTC), profit=15.0
    )
    broker = FakeBroker(open_positions=[], close_info={7: close_info})
    event_bus = EventBus()
    published: list[PositionClosed] = []

    async def on_closed(event: PositionClosed) -> None:
        published.append(event)

    event_bus.subscribe(PositionClosed, on_closed)
    reconciliation = ReconciliationService(broker=broker, journal=journal, event_bus=event_bus)

    await reconciliation.reconcile_vanished("XAUUSD", {7})

    assert len(published) == 1
    assert published[0].position_id == "7"
    assert published[0].profit == 15.0
