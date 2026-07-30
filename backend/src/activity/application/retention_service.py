"""Purges old `activity_logs` rows so the table — diagnostic-only and
otherwise unbounded — doesn't grow forever (see `configs/maintenance.yaml`).
Runs process-wide, across every account, unlike `ActivityLogService` which
is scoped to one account's UI queries. Same start/stop/_run background-task
shape as `NewsWindowService`/`GatewayHealthMonitor`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from src.activity.adapters.repository import ActivityLogRepository

logger = logging.getLogger(__name__)


class ActivityLogRetentionService:
    def __init__(
        self,
        repository: ActivityLogRepository,
        retention_days: int,
        check_interval_s: float,
    ) -> None:
        self._repository = repository
        self._retention_days = retention_days
        self._check_interval_s = check_interval_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="activity-log-retention")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await self.purge_once()
            await asyncio.sleep(self._check_interval_s)

    async def purge_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = int((now - timedelta(days=self._retention_days)).timestamp())
        try:
            deleted = await asyncio.to_thread(self._repository.delete_older_than, cutoff)
        except Exception:
            logger.exception("activity log retention purge failed")
            return 0
        if deleted:
            logger.info(
                "activity log retention: purged %d row(s) older than %d days",
                deleted,
                self._retention_days,
            )
        return deleted
