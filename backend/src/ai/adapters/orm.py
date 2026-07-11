"""AI draft table (§8.1): PDF-derived StrategySpec drafts awaiting review."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class AiDraftRow(Base):
    __tablename__ = "ai_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    extracted_spec: Mapped[dict] = mapped_column(JSON)
    edited_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
