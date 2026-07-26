"""Trade journal table — F5/F7 source of truth."""

from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class TradeRow(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))
    volume: Mapped[float] = mapped_column(Float)
    open_price: Mapped[float] = mapped_column(Float)
    open_time: Mapped[int] = mapped_column(Integer)
    sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_points_at_entry: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(255), default="")
    strategy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    m5_entry_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    h1_entry_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    m5_exit_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    h1_exit_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(500), default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    zone_price_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_price_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_time_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_time_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pattern: Mapped[str | None] = mapped_column(String(64), nullable=True)
    structure: Mapped[list] = mapped_column(JSON, default=list)
