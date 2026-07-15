"""Activity log query use case: read-only search over persisted bot logs
(§ "know what it's doing now and why" — see `shared/logging` for how entries
get written)."""

from __future__ import annotations

import asyncio

from src.activity.adapters.repository import ActivityLogRepository
from src.activity.domain.models import LogEntry


class ActivityLogService:
    def __init__(self, repository: ActivityLogRepository) -> None:
        self._repository = repository

    async def search(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[LogEntry], int]:
        return await asyncio.to_thread(
            self._repository.search,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )

    async def delete_by_ids(self, ids: list[int]) -> int:
        return await asyncio.to_thread(self._repository.delete_by_ids, ids)

    async def delete_by_filter(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._repository.delete_by_filter,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
        )
