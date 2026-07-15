"""Indicator persistence (sync SQLAlchemy; mirrors
`strategies/adapters/repository.py`)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.indicators.adapters.orm import IndicatorRow
from src.indicators.domain.models import IndicatorDefinition


class IndicatorRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, definition: IndicatorDefinition) -> None:
        row = _to_row(definition)
        with self._session_factory() as session:
            session.merge(row)
            session.commit()

    def get(self, indicator_id: str) -> IndicatorDefinition | None:
        with self._session_factory() as session:
            row = session.get(IndicatorRow, indicator_id)
        return _to_domain(row) if row else None

    def get_by_name(self, name: str) -> IndicatorDefinition | None:
        with self._session_factory() as session:
            row = session.scalars(select(IndicatorRow).where(IndicatorRow.name == name)).first()
        return _to_domain(row) if row else None

    def delete(self, indicator_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(IndicatorRow, indicator_id)
            if row is not None:
                session.delete(row)
                session.commit()

    def list_all(self) -> list[IndicatorDefinition]:
        query = select(IndicatorRow).order_by(IndicatorRow.name)
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]


def _to_row(definition: IndicatorDefinition) -> IndicatorRow:
    return IndicatorRow(
        id=definition.id,
        name=definition.name,
        code=definition.code,
        code_hash=definition.code_hash,
        default_params=definition.default_params,
        created_at=int(definition.created_at.timestamp()),
        updated_at=int(definition.updated_at.timestamp()),
    )


def _to_domain(row: IndicatorRow) -> IndicatorDefinition:
    return IndicatorDefinition(
        id=row.id,
        name=row.name,
        code=row.code,
        code_hash=row.code_hash,
        default_params=row.default_params or {},
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        updated_at=datetime.fromtimestamp(row.updated_at, tz=UTC),
    )
