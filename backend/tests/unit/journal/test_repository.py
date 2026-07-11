from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.journal.adapters.repository import JournalRepository
from src.journal.domain.models import CandleSnapshot, TradeRecord
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> JournalRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return JournalRepository(sessionmaker(bind=engine, expire_on_commit=False))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def make_record(id: str, symbol: str = "XAUUSD", open_time=None, **kw) -> TradeRecord:
    defaults = dict(
        id=id,
        symbol=symbol,
        side="buy",
        volume=0.1,
        open_price=2400.35,
        open_time=open_time or utc(2026, 7, 10, 14, 0),
        sl=2390.0,
        tp=2420.0,
        spread_points_at_entry=25,
        comment="",
    )
    return TradeRecord(**{**defaults, **kw})


def test_roundtrip_preserves_trade(repository):
    record = make_record("1")
    repository.save(record)
    assert repository.get("1") == record


def test_roundtrip_preserves_snapshots(repository):
    snapshot = (
        CandleSnapshot(
            time=utc(2026, 7, 10, 13, 55), open=1, high=2, low=0.5, close=1.5, tick_volume=100
        ),
    )
    record = make_record("1", m5_entry_snapshot=snapshot, h1_entry_snapshot=snapshot)
    repository.save(record)
    stored = repository.get("1")
    assert stored.m5_entry_snapshot == snapshot
    assert stored.h1_entry_snapshot == snapshot


def test_get_returns_none_for_unknown_id(repository):
    assert repository.get("missing") is None


def test_save_upserts_same_id(repository):
    repository.save(make_record("1"))
    repository.save(make_record("1", close_price=2410.0, close_time=utc(2026, 7, 10, 15, 0)))

    stored = repository.get("1")
    assert stored.close_price == 2410.0
    assert stored.is_open is False


def test_get_last_n_orders_by_open_time_desc(repository):
    for i, minute in enumerate((0, 5, 10)):
        repository.save(make_record(str(i), open_time=utc(2026, 7, 10, 14, minute)))

    last_two = repository.get_last_n("XAUUSD", 2)
    assert [r.id for r in last_two] == ["2", "1"]


def test_get_markers_filters_by_time_range(repository):
    for i, minute in enumerate((0, 5, 10)):
        repository.save(make_record(str(i), open_time=utc(2026, 7, 10, 14, minute)))

    frm = int(utc(2026, 7, 10, 14, 5).timestamp())
    markers = repository.get_markers("XAUUSD", frm=frm)
    assert [r.id for r in markers] == ["1", "2"]


def test_count_closed_only_counts_closed_trades(repository):
    repository.save(make_record("1"))
    repository.save(
        make_record("2", close_price=2410.0, close_time=utc(2026, 7, 10, 15, 0), profit=9.65)
    )
    assert repository.count_closed("XAUUSD") == 1


def test_get_last_n_closed_orders_by_close_time_desc(repository):
    repository.save(
        make_record("1", close_price=2410.0, close_time=utc(2026, 7, 10, 15, 0), profit=9.65)
    )
    repository.save(
        make_record("2", close_price=2405.0, close_time=utc(2026, 7, 10, 16, 0), profit=4.65)
    )
    repository.save(make_record("3"))  # still open, excluded

    closed = repository.get_last_n_closed("XAUUSD", 10)
    assert [r.id for r in closed] == ["2", "1"]
