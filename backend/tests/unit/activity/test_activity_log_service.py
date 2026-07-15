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
