from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.market_data.adapters.candle_repository import CandleRepository
from src.market_data.domain.models import Timeframe
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> CandleRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return CandleRepository(sessionmaker(bind=engine, expire_on_commit=False))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_roundtrip_preserves_candle(repository, candle_factory):
    candle = candle_factory(utc(2026, 7, 10, 14, 0))
    assert repository.upsert_many([candle]) == 1
    assert repository.get_latest("XAUUSD", Timeframe.M5, 10) == [candle]


def test_upsert_overwrites_same_bar(repository, candle_factory):
    time = utc(2026, 7, 10, 14, 0)
    repository.upsert_many([candle_factory(time, close=2400.5)])
    repository.upsert_many([candle_factory(time, close=2410.0)])

    (stored,) = repository.get_latest("XAUUSD", Timeframe.M5, 10)
    assert stored.close == 2410.0


def test_get_latest_returns_most_recent_oldest_first(repository, candle_factory):
    times = [utc(2026, 7, 10, 14, m) for m in (0, 5, 10, 15)]
    repository.upsert_many([candle_factory(t) for t in times])

    stored = repository.get_latest("XAUUSD", Timeframe.M5, 2)
    assert [c.time for c in stored] == times[-2:]


def test_get_before_returns_bars_strictly_before_cutoff_oldest_first(repository, candle_factory):
    times = [utc(2026, 7, 10, 14, m) for m in (0, 5, 10, 15)]
    repository.upsert_many([candle_factory(t) for t in times])

    stored = repository.get_before("XAUUSD", Timeframe.M5, utc(2026, 7, 10, 14, 10), 10)
    assert [c.time for c in stored] == times[:2]


def test_get_before_respects_count(repository, candle_factory):
    times = [utc(2026, 7, 10, 14, m) for m in (0, 5, 10, 15)]
    repository.upsert_many([candle_factory(t) for t in times])

    stored = repository.get_before("XAUUSD", Timeframe.M5, utc(2026, 7, 10, 14, 15), 2)
    assert [c.time for c in stored] == times[1:3]


def test_get_range_bounds_are_start_inclusive_end_exclusive(repository, candle_factory):
    times = [utc(2026, 7, 10, 14, m) for m in (0, 5, 10, 15)]
    repository.upsert_many([candle_factory(t) for t in times])

    stored = repository.get_range(
        "XAUUSD", Timeframe.M5, utc(2026, 7, 10, 14, 5), utc(2026, 7, 10, 14, 15)
    )
    assert [c.time for c in stored] == times[1:3]


def test_get_range_returns_oldest_first(repository, candle_factory):
    times = [utc(2026, 7, 10, 14, m) for m in (10, 0, 5)]
    repository.upsert_many([candle_factory(t) for t in times])

    stored = repository.get_range(
        "XAUUSD", Timeframe.M5, utc(2026, 7, 10, 13, 0), utc(2026, 7, 10, 15, 0)
    )
    assert [c.time for c in stored] == sorted(times)


def test_symbols_and_timeframes_are_isolated(repository, candle_factory):
    time = utc(2026, 7, 10, 14, 0)
    repository.upsert_many(
        [
            candle_factory(time, symbol="XAUUSD"),
            candle_factory(time, symbol="BTCUSD"),
            candle_factory(utc(2026, 7, 10, 14, 0), timeframe=Timeframe.H1),
        ]
    )
    assert len(repository.get_latest("XAUUSD", Timeframe.M5, 10)) == 1
    assert len(repository.get_latest("BTCUSD", Timeframe.M5, 10)) == 1
    assert len(repository.get_latest("XAUUSD", Timeframe.H1, 10)) == 1


def test_bars_are_keyed_per_account(repository, candle_factory):
    """Different brokers quote different spreads/prices for a nominally
    identical symbol (e.g. `XAUUSD` vs `XAUUSD.a`) — a shared cache keyed
    only on (symbol, timeframe, time) would silently mix them."""
    time = utc(2026, 7, 10, 14, 0)
    repository.upsert_many([candle_factory(time, close=2400.5)], account_id="ftmo-1")
    repository.upsert_many([candle_factory(time, close=2410.0)], account_id="ftmo-2")

    (ftmo_1,) = repository.get_latest("XAUUSD", Timeframe.M5, 10, account_id="ftmo-1")
    (ftmo_2,) = repository.get_latest("XAUUSD", Timeframe.M5, 10, account_id="ftmo-2")
    assert ftmo_1.close == 2400.5
    assert ftmo_2.close == 2410.0
    assert repository.get_latest("XAUUSD", Timeframe.M5, 10, account_id="default") == []
