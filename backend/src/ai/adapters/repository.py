"""AI draft persistence (sync SQLAlchemy; call via asyncio.to_thread)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.ai.adapters.orm import AiDraftRow
from src.ai.domain.models import DraftStatus, ExtractedStrategySpec, StrategyDraft


class DraftRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, draft: StrategyDraft) -> None:
        row = _to_row(draft)
        with self._session_factory() as session:
            session.merge(row)
            session.commit()

    def get(self, draft_id: str) -> StrategyDraft | None:
        with self._session_factory() as session:
            row = session.get(AiDraftRow, draft_id)
        return _to_domain(row) if row else None

    def list_all(self) -> list[StrategyDraft]:
        query = select(AiDraftRow).order_by(AiDraftRow.created_at.desc())
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]


def _to_row(draft: StrategyDraft) -> AiDraftRow:
    return AiDraftRow(
        id=draft.id,
        source_filename=draft.source_filename,
        created_at=int(draft.created_at.timestamp()),
        status=draft.status.value,
        extracted_spec=draft.extracted_spec.to_dict(),
        edited_spec=draft.edited_spec.to_dict() if draft.edited_spec else None,
    )


def _to_domain(row: AiDraftRow) -> StrategyDraft:
    return StrategyDraft(
        id=row.id,
        source_filename=row.source_filename,
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        status=DraftStatus(row.status),
        extracted_spec=ExtractedStrategySpec.from_dict(row.extracted_spec),
        edited_spec=ExtractedStrategySpec.from_dict(row.edited_spec) if row.edited_spec else None,
    )
