"""Strategy version table (§6.5, §8.1)."""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class StrategyVersionRow(Base):
    __tablename__ = "strategy_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(255))
    code_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    backtest_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
