"""Persistence for candle history (sync SQLAlchemy; call via asyncio.to_thread)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from src.market_data.adapters.orm import CandleRow
from src.market_data.domain.models import Candle, Timeframe


class CandleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_many(self, candles: Iterable[Candle]) -> int:
        """Insert or refresh bars (re-downloads and the forming bar overwrite)."""
        rows = [
            {
                "symbol": c.symbol,
                "timeframe": c.timeframe.value,
                "time": int(c.time.timestamp()),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "tick_volume": c.tick_volume,
                "spread_points": c.spread_points,
            }
            for c in candles
        ]
        if not rows:
            return 0
        # SQLite-dialect upsert; swap for postgresql.insert when the DB moves.
        statement = insert(CandleRow)
        statement = statement.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "time"],
            set_={
                col: statement.excluded[col]
                for col in ("open", "high", "low", "close", "tick_volume", "spread_points")
            },
        )
        with self._session_factory() as session:
            session.execute(statement, rows)
            session.commit()
        return len(rows)

    def get_latest(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        """Most recent `count` stored bars, oldest first."""
        query = (
            select(CandleRow)
            .where(CandleRow.symbol == symbol, CandleRow.timeframe == timeframe.value)
            .order_by(CandleRow.time.desc())
            .limit(count)
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in reversed(rows)]

    def get_range(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Stored bars with open time in `[start, end)`, oldest first — used
        by the backtest replay adapter to load a bounded historical window."""
        query = (
            select(CandleRow)
            .where(
                CandleRow.symbol == symbol,
                CandleRow.timeframe == timeframe.value,
                CandleRow.time >= int(start.timestamp()),
                CandleRow.time < int(end.timestamp()),
            )
            .order_by(CandleRow.time.asc())
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]


def _to_domain(row: CandleRow) -> Candle:
    return Candle(
        symbol=row.symbol,
        timeframe=Timeframe(row.timeframe),
        time=datetime.fromtimestamp(row.time, tz=UTC),
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        tick_volume=row.tick_volume,
        spread_points=row.spread_points,
    )
