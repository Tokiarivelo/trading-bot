"""Activity log query use case: read-only search over persisted bot logs
(§ "know what it's doing now and why" — see `shared/logging` for how entries
get written)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from src.activity.adapters.repository import ActivityLogRepository
from src.activity.application.bot_signals import extract_bot_signals
from src.activity.domain.models import BotSignal, LogEntry

# How far back to look when the caller doesn't specify a range — bounds the
# query on a potentially large table without requiring every caller to know
# a sensible window.
_DEFAULT_SIGNAL_WINDOW = timedelta(days=14)

# The only loggers a bot's own decision-trail lines (SIGNAL/ENTRY */SIZING OK)
# ever come from — see `activity.application.bot_signals` module docstring.
_SIGNAL_LOGGERS = ("src.engine.application.trade_loop", "src.broker.application.order_service")


class ActivityLogService:
    def __init__(self, repository: ActivityLogRepository, account_id: str = "default") -> None:
        self._repository = repository
        self._account_id = account_id

    async def get_bot_signals(
        self, *, skill: str, created_from: int | None = None, created_to: int | None = None
    ) -> list[BotSignal]:
        """Reconstructs `skill`'s own signal→outcome trail — see
        `bot_signals.extract_bot_signals` for why this needs the skill scope
        rather than a plain time-range log search."""
        if created_from is None:
            created_from = int((datetime.now(UTC) - _DEFAULT_SIGNAL_WINDOW).timestamp())
        entries: list[LogEntry] = []
        for logger_name in _SIGNAL_LOGGERS:
            rows, _total = await asyncio.to_thread(
                self._repository.search,
                logger_contains=logger_name,
                created_from=created_from,
                created_to=created_to,
                limit=5000,
                account_id=self._account_id,
            )
            entries.extend(rows)
        entries.sort(key=lambda e: (e.created_at, e.id or 0))
        return extract_bot_signals(entries, skill)

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
            account_id=self._account_id,
        )

    async def delete_by_ids(self, ids: list[int]) -> int:
        return await asyncio.to_thread(self._repository.delete_by_ids, ids, self._account_id)

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
            account_id=self._account_id,
        )
