from datetime import UTC, datetime

from src.activity.application.retention_service import ActivityLogRetentionService

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.deleted = 0

    def delete_older_than(self, cutoff_timestamp: int) -> int:
        self.calls.append(cutoff_timestamp)
        return self.deleted


async def test_purge_once_deletes_rows_older_than_retention_window():
    repository = FakeRepository()
    repository.deleted = 3
    service = ActivityLogRetentionService(repository, retention_days=90, check_interval_s=3600)

    deleted = await service.purge_once(now=NOW)

    assert deleted == 3
    expected_cutoff = int(datetime(2026, 4, 29, 12, 0, tzinfo=UTC).timestamp())
    assert repository.calls == [expected_cutoff]


async def test_purge_once_swallows_repository_errors():
    class FailingRepository(FakeRepository):
        def delete_older_than(self, cutoff_timestamp: int) -> int:
            raise RuntimeError("db locked")

    service = ActivityLogRetentionService(
        FailingRepository(), retention_days=90, check_interval_s=3600
    )

    deleted = await service.purge_once(now=NOW)

    assert deleted == 0


async def test_start_and_stop_manage_the_background_task():
    repository = FakeRepository()
    service = ActivityLogRetentionService(repository, retention_days=90, check_interval_s=3600)

    service.start()
    assert service._task is not None
    await service.stop()
    assert service._task is None
