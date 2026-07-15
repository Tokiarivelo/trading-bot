import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.activity.adapters.repository import ActivityLogRepository
from src.shared.db.base import Base


@pytest.fixture
def repository(tmp_path) -> ActivityLogRepository:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return ActivityLogRepository(sessionmaker(bind=engine, expire_on_commit=False))


def test_search_returns_saved_entries_newest_first(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="first")
    repository.save(created_at=200, level="INFO", logger="src.engine", message="second")

    entries, total = repository.search()

    assert total == 2
    assert [e.message for e in entries] == ["second", "first"]


def test_search_filters_by_level(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="ok")
    repository.save(created_at=200, level="WARNING", logger="src.engine", message="uh oh")

    entries, total = repository.search(level="warning")

    assert total == 1
    assert entries[0].message == "uh oh"


def test_search_filters_by_logger_substring(repository):
    repository.save(
        created_at=100, level="INFO", logger="src.engine.application.trade_loop", message="a"
    )
    repository.save(
        created_at=200, level="INFO", logger="src.broker.application.order_service", message="b"
    )

    entries, total = repository.search(logger_contains="broker")

    assert total == 1
    assert entries[0].message == "b"


def test_search_filters_by_message_substring(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="signal: XAUUSD buy")
    repository.save(
        created_at=200, level="INFO", logger="src.engine", message="signal: EURUSD sell"
    )

    entries, total = repository.search(q="XAUUSD")

    assert total == 1
    assert entries[0].message == "signal: XAUUSD buy"


def test_search_filters_by_time_range(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="early")
    repository.save(created_at=200, level="INFO", logger="src.engine", message="late")

    entries, total = repository.search(created_from=150)

    assert total == 1
    assert entries[0].message == "late"


def test_search_paginates(repository):
    for i in range(5):
        repository.save(created_at=i, level="INFO", logger="src.engine", message=f"m{i}")

    page, total = repository.search(limit=2, offset=1)

    assert total == 5
    assert [e.message for e in page] == ["m3", "m2"]


def test_delete_by_ids_removes_only_given_rows(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="keep")
    repository.save(created_at=200, level="INFO", logger="src.engine", message="drop")
    entries, _ = repository.search()
    drop_id = next(e.id for e in entries if e.message == "drop")

    deleted = repository.delete_by_ids([drop_id])

    remaining, total = repository.search()
    assert deleted == 1
    assert total == 1
    assert remaining[0].message == "keep"


def test_delete_by_ids_with_no_ids_deletes_nothing(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="keep")

    deleted = repository.delete_by_ids([])

    _, total = repository.search()
    assert deleted == 0
    assert total == 1


def test_delete_by_filter_removes_matching_rows_only(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="ok")
    repository.save(created_at=200, level="WARNING", logger="src.engine", message="uh oh")

    deleted = repository.delete_by_filter(level="warning")

    _, total = repository.search()
    assert deleted == 1
    assert total == 1


def test_delete_by_filter_with_no_filters_deletes_everything(repository):
    repository.save(created_at=100, level="INFO", logger="src.engine", message="a")
    repository.save(created_at=200, level="INFO", logger="src.engine", message="b")

    deleted = repository.delete_by_filter()

    _, total = repository.search()
    assert deleted == 2
    assert total == 0
