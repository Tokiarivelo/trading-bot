"""Per-task provider override persistence (AI_PROVIDER_SETTINGS_PLAN.md §6.3),
sync SQLAlchemy; call via asyncio.to_thread — mirrors `ai/adapters/repository.py`'s
DraftRepository.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.ai.adapters.orm import TaskProviderOverrideRow
from src.ai.domain.provider_config import TaskProviderOverride


class ProviderConfigRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_all(self) -> dict[str, TaskProviderOverride]:
        with self._session_factory() as session:
            rows = session.scalars(select(TaskProviderOverrideRow)).all()
        return {row.task: _to_domain(row) for row in rows}

    def set(self, task: str, provider: str, model: str) -> TaskProviderOverride:
        override = TaskProviderOverride(
            task=task, provider=provider, model=model, updated_at=datetime.now(UTC)
        )
        with self._session_factory() as session:
            session.merge(_to_row(override))
            session.commit()
        return override

    def clear(self, task: str) -> None:
        with self._session_factory() as session:
            row = session.get(TaskProviderOverrideRow, task)
            if row is not None:
                session.delete(row)
                session.commit()


def _to_row(override: TaskProviderOverride) -> TaskProviderOverrideRow:
    return TaskProviderOverrideRow(
        task=override.task,
        provider=override.provider,
        model=override.model,
        updated_at=int(override.updated_at.timestamp()),
    )


def _to_domain(row: TaskProviderOverrideRow) -> TaskProviderOverride:
    return TaskProviderOverride(
        task=row.task,
        provider=row.provider,
        model=row.model,
        updated_at=datetime.fromtimestamp(row.updated_at, tz=UTC),
    )
