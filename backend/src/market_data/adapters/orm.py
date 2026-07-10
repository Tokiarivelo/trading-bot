"""Candle history table — backtests and AI snapshots read from here."""

from __future__ import annotations

from sqlalchemy import BigInteger, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.db.base import Base


class CandleRow(Base):
    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    # Bar open time as epoch seconds UTC — matches the wire format and
    # lightweight-charts, and keeps SQLite/PostgreSQL behavior identical.
    time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    tick_volume: Mapped[int] = mapped_column(Integer)
    spread_points: Mapped[int] = mapped_column(Integer)
