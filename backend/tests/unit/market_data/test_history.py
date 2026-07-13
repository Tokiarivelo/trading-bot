from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.market_data.adapters.symbol_spec_repository import SymbolSpecRepository
from src.market_data.application.history import CandleHistoryService
from src.market_data.domain.models import Candle, SymbolInfo, Timeframe
from src.shared.db.base import Base


class FakeMarketData:
    """Stub `MarketDataPort` — only `get_symbol_info` is exercised here."""

    def __init__(self, info: SymbolInfo) -> None:
        self._info = info

    async def get_candles(self, symbol, timeframe, count, before=None):
        raise NotImplementedError

    async def get_tick(self, symbol):
        raise NotImplementedError

    async def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return self._info


class FakePagingMarketData:
    """Stub `MarketDataPort` that mimics the gateway's `before`-cursor paging:
    given a full ascending-by-time history, returns up to `count` bars
    strictly before `before` (or the most recent `count` bars if `before` is
    None), newest last — same contract as `GatewayMarketData.get_candles`."""

    def __init__(self, bars: list[Candle]) -> None:
        self._bars = bars  # ascending by time
        self.calls: list[datetime | None] = []

    async def get_candles(self, symbol, timeframe, count, before=None):
        self.calls.append(before)
        if before is None:
            return self._bars[-count:]
        cutoff = next(
            (i for i, c in enumerate(self._bars) if c.time >= before), len(self._bars)
        )
        return self._bars[:cutoff][-count:]

    async def get_tick(self, symbol):
        raise NotImplementedError

    async def get_symbol_info(self, symbol):
        raise NotImplementedError


class FakeCandleRepository:
    def __init__(self) -> None:
        self.stored: list[Candle] = []

    def upsert_many(self, candles) -> int:
        candles = list(candles)
        self.stored.extend(candles)
        return len(candles)


def make_bars(count: int, *, start: datetime, timeframe: Timeframe = Timeframe.M5) -> list[Candle]:
    return [
        Candle(
            symbol="XAUUSD",
            timeframe=timeframe,
            time=start + i * timedelta(seconds=timeframe.seconds),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            tick_volume=1,
            spread_points=1,
        )
        for i in range(count)
    ]


def make_info(**overrides) -> SymbolInfo:
    defaults = dict(
        symbol="Volatility 75 Index",
        bid=245678.10,
        ask=245678.35,
        spread_points=25,
        point=0.01,
        digits=2,
        stops_level=0,
        contract_size=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    return SymbolInfo(**{**defaults, **overrides})


@pytest.fixture
def symbol_spec_repository(tmp_path) -> SymbolSpecRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return SymbolSpecRepository(sessionmaker(bind=engine, expire_on_commit=False))


async def test_sync_symbol_spec_persists_gateway_facts(symbol_spec_repository):
    service = CandleHistoryService(
        FakeMarketData(make_info()), repository=None, symbol_spec_repository=symbol_spec_repository
    )

    await service.sync_symbol_spec("Volatility 75 Index")

    stored = symbol_spec_repository.get("Volatility 75 Index")
    assert stored is not None
    assert stored.point == 0.01
    assert stored.digits == 2
    assert stored.contract_size == 1.0
    assert stored.volume_min == 0.01


async def test_sync_symbol_spec_without_repository_does_not_raise():
    service = CandleHistoryService(FakeMarketData(make_info()), repository=None)
    await service.sync_symbol_spec("Volatility 75 Index")  # no-ops, doesn't crash


async def test_backfill_without_start_fetches_only_most_recent_page():
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    bars = make_bars(250, start=origin)
    market_data = FakePagingMarketData(bars)
    repository = FakeCandleRepository()
    service = CandleHistoryService(market_data, repository)

    stored = await service.backfill("XAUUSD", Timeframe.M5, 100)

    assert stored == 100
    assert market_data.calls == [None]
    assert repository.stored == bars[-100:]


async def test_backfill_with_start_pages_backward_until_range_is_covered():
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    bars = make_bars(250, start=origin)  # 250 * 5min spans well past `origin`
    market_data = FakePagingMarketData(bars)
    repository = FakeCandleRepository()
    service = CandleHistoryService(market_data, repository)

    stored = await service.backfill("XAUUSD", Timeframe.M5, 100, start=origin)

    # 3 pages of <=100 to cover all 250 bars back to `origin`.
    assert stored == 250
    assert len(market_data.calls) == 3
    assert sorted(repository.stored, key=lambda c: c.time) == bars


async def test_backfill_with_start_stops_when_broker_history_runs_out():
    origin = datetime(2026, 1, 1, tzinfo=UTC)
    bars = make_bars(50, start=origin)
    market_data = FakePagingMarketData(bars)
    repository = FakeCandleRepository()
    service = CandleHistoryService(market_data, repository)

    # Requested start is far earlier than any real history — pagination must
    # stop once the broker returns a short (final) page, not loop forever.
    stored = await service.backfill(
        "XAUUSD", Timeframe.M5, 100, start=origin - timedelta(days=365)
    )

    assert stored == 50
    assert len(market_data.calls) == 1
