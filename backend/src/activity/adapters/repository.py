"""Activity log persistence (sync SQLAlchemy; call via asyncio.to_thread from
the application layer — the log handler itself runs on its own thread, see
`shared/logging/adapters/handler.py`, so it writes directly)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.activity.adapters.orm import LogRow
from src.activity.domain.models import LogEntry


def _build_filters(
    *,
    account_id: str,
    level: str | None,
    logger_contains: str | None,
    q: str | None,
    created_from: int | None,
    created_to: int | None,
) -> list[ColumnElement]:
    filters: list[ColumnElement] = [LogRow.account_id == account_id]
    if level is not None:
        filters.append(LogRow.level == level.upper())
    if logger_contains is not None:
        filters.append(LogRow.logger.contains(logger_contains))
    if q is not None:
        filters.append(LogRow.message.contains(q))
    if created_from is not None:
        filters.append(LogRow.created_at >= created_from)
    if created_to is not None:
        filters.append(LogRow.created_at <= created_to)
    return filters


class ActivityLogRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(
        self,
        *,
        created_at: int,
        level: str,
        logger: str,
        message: str,
        account_id: str = "default",
    ) -> None:
        with self._session_factory() as session:
            session.add(
                LogRow(
                    account_id=account_id,
                    created_at=created_at,
                    level=level,
                    logger=logger,
                    message=message,
                )
            )
            session.commit()

    def search(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        limit: int = 100,
        offset: int = 0,
        account_id: str = "default",
    ) -> tuple[list[LogEntry], int]:
        """Filterable, paginated log history query — backs `GET /activity/history`."""
        filters = _build_filters(
            account_id=account_id,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
        )

        count_query = select(func.count()).select_from(LogRow).where(*filters)
        page_query = (
            select(LogRow).where(*filters).order_by(LogRow.id.desc()).limit(limit).offset(offset)
        )
        with self._session_factory() as session:
            total = session.scalar(count_query) or 0
            rows = session.scalars(page_query).all()
        return [_to_domain(row) for row in rows], total

    def delete_by_ids(self, ids: list[int], account_id: str = "default") -> int:
        """Deletes specific log rows by id — backs single-row delete and the
        multi-select bulk delete in the activity log UI. Scoped to
        `account_id` so a bulk delete issued while viewing one account can
        never remove another account's rows."""
        if not ids:
            return 0
        with self._session_factory() as session:
            result = session.execute(
                delete(LogRow).where(LogRow.id.in_(ids), LogRow.account_id == account_id)
            )
            session.commit()
            return result.rowcount or 0

    def delete_by_filter(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        account_id: str = "default",
    ) -> int:
        """Deletes every log row matching the given filters — backs
        "delete all matching" in the activity log UI. Uses the same filter
        semantics as `search`, with no filters at all deleting every row."""
        filters = _build_filters(
            account_id=account_id,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
        )
        with self._session_factory() as session:
            result = session.execute(delete(LogRow).where(*filters))
            session.commit()
            return result.rowcount or 0


def _to_domain(row: LogRow) -> LogEntry:
    return LogEntry(
        id=row.id,
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        level=row.level,
        logger=row.logger,
        message=row.message,
    )
