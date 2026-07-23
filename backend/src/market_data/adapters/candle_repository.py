"""Persistence for candle history (sync SQLAlchemy; call via asyncio.to_thread)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import Row, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from src.market_data.adapters.orm import CandleRow
from src.market_data.domain.models import Candle, Timeframe

# Read queries select these columns as plain tuples instead of materializing
# ORM `CandleRow` instances — candle reads are the backtest runner's single
# biggest fixed cost (hundreds of thousands of rows per run), and identity-map
# bookkeeping buys nothing for immutable history rows that are never updated
# through the session.
_CANDLE_COLUMNS = (
    CandleRow.time,
    CandleRow.open,
    CandleRow.high,
    CandleRow.low,
    CandleRow.close,
    CandleRow.tick_volume,
    CandleRow.spread_points,
)


class CandleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_many(self, candles: Iterable[Candle], account_id: str = "default") -> int:
        """Insert or refresh bars (re-downloads and the forming bar overwrite)."""
        rows = [
            {
                "account_id": account_id,
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
            index_elements=["account_id", "symbol", "timeframe", "time"],
            set_={
                col: statement.excluded[col]
                for col in ("open", "high", "low", "close", "tick_volume", "spread_points")
            },
        )
        with self._session_factory() as session:
            session.execute(statement, rows)
            session.commit()
        return len(rows)

    def get_latest(
        self, symbol: str, timeframe: Timeframe, count: int, account_id: str = "default"
    ) -> list[Candle]:
        """Most recent `count` stored bars, oldest first."""
        query = (
            select(*_CANDLE_COLUMNS)
            .where(
                CandleRow.symbol == symbol,
                CandleRow.timeframe == timeframe.value,
                CandleRow.account_id == account_id,
            )
            .order_by(CandleRow.time.desc())
            .limit(count)
        )
        with self._session_factory() as session:
            rows = session.execute(query).all()
        return _to_domain_many(symbol, timeframe, reversed(rows))

    def get_before(
        self,
        symbol: str,
        timeframe: Timeframe,
        before: datetime,
        count: int,
        account_id: str = "default",
    ) -> list[Candle]:
        """`count` stored bars with open time strictly before `before`, oldest
        first — for paging further back in history than `get_latest`."""
        query = (
            select(*_CANDLE_COLUMNS)
            .where(
                CandleRow.symbol == symbol,
                CandleRow.timeframe == timeframe.value,
                CandleRow.time < int(before.timestamp()),
                CandleRow.account_id == account_id,
            )
            .order_by(CandleRow.time.desc())
            .limit(count)
        )
        with self._session_factory() as session:
            rows = session.execute(query).all()
        return _to_domain_many(symbol, timeframe, reversed(rows))

    def get_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        account_id: str = "default",
    ) -> list[Candle]:
        """Stored bars with open time in `[start, end)`, oldest first — used
        by the backtest replay adapter to load a bounded historical window."""
        query = (
            select(*_CANDLE_COLUMNS)
            .where(
                CandleRow.symbol == symbol,
                CandleRow.timeframe == timeframe.value,
                CandleRow.time >= int(start.timestamp()),
                CandleRow.time < int(end.timestamp()),
                CandleRow.account_id == account_id,
            )
            .order_by(CandleRow.time.asc())
        )
        with self._session_factory() as session:
            rows = session.execute(query).all()
        return _to_domain_many(symbol, timeframe, rows)


def _to_domain_many(symbol: str, timeframe: Timeframe, rows: Iterable[Row]) -> list[Candle]:
    return [
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            time=datetime.fromtimestamp(time, tz=UTC),
            open=open_,
            high=high,
            low=low,
            close=close,
            tick_volume=tick_volume,
            spread_points=spread_points,
        )
        for time, open_, high, low, close, tick_volume, spread_points in rows
    ]
