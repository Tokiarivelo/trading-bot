"""Activity tables — persisted mirror of `src.*` application logs, plus the
typed signal-decision trail the engine writes directly."""

from __future__ import annotations

from sqlalchemy import JSON, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class LogRow(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[str] = mapped_column(String(10), index=True)
    logger: Mapped[str] = mapped_column(String(128), index=True)
    message: Mapped[str] = mapped_column(Text)
    signal_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    """Correlation id (OBSERVABILITY_PLAN.md Phase 5) — set on every log line
    emitted while `shared.logging.account_context.current_signal_id` is bound
    (see `TradeEngine._try_enter`), `None` for lines outside a signal's
    processing window (most of them: health checks, candle polling, ...).
    `GET /activity/history?signal_id=...` filters on this to read one
    signal's whole life in order."""


class SignalDecisionRow(Base):
    """One `SignalDecision` — the typed decision trail (see
    `activity/domain/models.py`). Written by the engine/broker through
    `SignalDecisionSinkPort` the moment a signal fires, then updated in place
    with its terminal outcome."""

    __tablename__ = "signal_decisions"
    __table_args__ = (
        # The signal-trail read path is always "this bot, this time range,
        # oldest first" — see `SignalDecisionRepository.list_for_bot`.
        Index("ix_signal_decisions_account_bot_created", "account_id", "bot", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True)
    bot: Mapped[str] = mapped_column(String(255), index=True)
    strategy: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(8))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    checks: Mapped[list] = mapped_column(JSON, default=list)
    """`DecisionCheck` tuples as JSON arrays `[name, value, threshold,
    comparison, passed]` — same flat encoding `TradeRow.indicators` uses."""
