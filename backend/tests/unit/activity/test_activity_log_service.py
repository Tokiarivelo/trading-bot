from datetime import UTC, datetime

from src.activity.application.activity_log_service import ActivityLogService
from src.activity.domain.models import LogEntry


class FakeRepository:
    def __init__(self, entries, total, deleted=0):
        self.entries = entries
        self.total = total
        self.deleted = deleted
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return self.entries, self.total

    def delete_by_ids(self, ids):
        self.calls.append(("delete_by_ids", ids))
        return self.deleted

    def delete_by_filter(self, **kwargs):
        self.calls.append(("delete_by_filter", kwargs))
        return self.deleted


async def test_search_delegates_to_repository_and_returns_result():
    entry = LogEntry(id=1, created_at=datetime.now(UTC), level="INFO", logger="src.x", message="m")
    repository = FakeRepository([entry], 1)
    service = ActivityLogService(repository)

    entries, total = await service.search(level="INFO", q="m", limit=10, offset=0)

    assert entries == [entry]
    assert total == 1
    assert repository.calls[0] == ("search", repository.calls[0][1])
    assert repository.calls[0][1]["level"] == "INFO"
    assert repository.calls[0][1]["q"] == "m"


async def test_delete_by_ids_delegates_to_repository():
    repository = FakeRepository([], 0, deleted=2)
    service = ActivityLogService(repository)

    deleted = await service.delete_by_ids([1, 2])

    assert deleted == 2
    assert repository.calls == [("delete_by_ids", [1, 2])]


async def test_delete_by_filter_delegates_to_repository():
    repository = FakeRepository([], 0, deleted=3)
    service = ActivityLogService(repository)

    deleted = await service.delete_by_filter(level="WARNING", q="veto")

    assert deleted == 3
    assert repository.calls[0][0] == "delete_by_filter"
    assert repository.calls[0][1]["level"] == "WARNING"
    assert repository.calls[0][1]["q"] == "veto"


class FakeLoggerFilteringRepository:
    """Unlike `FakeRepository` above, filters by `logger_contains` like the
    real repository does — needed to test `get_bot_signals`, which queries
    the trade_loop and order_service loggers separately and merges."""

    def __init__(self, entries: list[LogEntry]) -> None:
        self.entries = entries
        self.calls = []

    def search(self, *, logger_contains=None, **kwargs):
        self.calls.append(("search", logger_contains, kwargs))
        rows = [e for e in self.entries if logger_contains in e.logger]
        return rows, len(rows)


def _log(seconds: int, logger: str, message: str) -> LogEntry:
    return LogEntry(
        id=seconds,
        created_at=datetime(2026, 7, 17, 12, 0, seconds, tzinfo=UTC),
        level="INFO",
        logger=logger,
        message=message,
    )


async def test_get_bot_signals_merges_both_loggers_in_time_order():
    skill = "normal/xauusd/breakout_v1"
    entries = [
        _log(
            0,
            "src.engine.application.trade_loop",
            f"SIGNAL: XAUUSD buy via strategy=breakout_v1 skill={skill} — retest",
        ),
        _log(
            1,
            "src.broker.application.order_service",
            f"ENTRY OPENED: ticket=1 buy XAUUSD 0.01 lots @ 4000.00 sl=None tp=None spread=1pts "
            f"strategy=breakout_v1:v1 skill={skill} magic=1 reason=retest",
        ),
    ]
    repository = FakeLoggerFilteringRepository(entries)
    service = ActivityLogService(repository)

    signals = await service.get_bot_signals(skill=skill)

    assert len(signals) == 1
    assert signals[0].outcome == "opened"
    queried_loggers = {call[1] for call in repository.calls}
    assert queried_loggers == {
        "src.engine.application.trade_loop",
        "src.broker.application.order_service",
    }


async def test_get_bot_signals_defaults_a_bounded_time_window():
    repository = FakeLoggerFilteringRepository([])
    service = ActivityLogService(repository)

    await service.get_bot_signals(skill="normal/xauusd/breakout_v1")

    for _, _, kwargs in repository.calls:
        assert kwargs["created_from"] is not None
