"""Trade record persistence (sync SQLAlchemy; call via asyncio.to_thread)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.journal.adapters.orm import TradeRow
from src.journal.domain.models import CandleSnapshot, TradeRecord


class JournalRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, record: TradeRecord) -> None:
        row = _to_row(record)
        with self._session_factory() as session:
            session.merge(row)
            session.commit()

    def get(self, trade_id: str) -> TradeRecord | None:
        with self._session_factory() as session:
            row = session.get(TradeRow, trade_id)
        return _to_domain(row) if row else None

    def get_last_n(self, symbol: str, count: int) -> list[TradeRecord]:
        query = (
            select(TradeRow)
            .where(TradeRow.symbol == symbol)
            .order_by(TradeRow.open_time.desc())
            .limit(count)
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]

    def get_markers(
        self, symbol: str, frm: int | None = None, to: int | None = None
    ) -> list[TradeRecord]:
        query = select(TradeRow).where(TradeRow.symbol == symbol).order_by(TradeRow.open_time)
        if frm is not None:
            query = query.where(TradeRow.open_time >= frm)
        if to is not None:
            query = query.where(TradeRow.open_time <= to)
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]

    def get_open(self, symbol: str | None = None) -> list[TradeRecord]:
        """Trades journaled as opened but never journaled as closed —
        candidates for reconciliation on startup/reconnect (Phase 9)."""
        query = select(TradeRow).where(TradeRow.close_time.is_(None))
        if symbol is not None:
            query = query.where(TradeRow.symbol == symbol)
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]

    def get_last_n_closed(self, symbol: str, count: int) -> list[TradeRecord]:
        query = (
            select(TradeRow)
            .where(TradeRow.symbol == symbol, TradeRow.close_time.is_not(None))
            .order_by(TradeRow.close_time.desc())
            .limit(count)
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]

    def count_closed(self, symbol: str) -> int:
        query = (
            select(func.count())
            .select_from(TradeRow)
            .where(TradeRow.symbol == symbol, TradeRow.close_time.is_not(None))
        )
        with self._session_factory() as session:
            return session.scalar(query) or 0


def _snapshot_to_json(snapshot: tuple[CandleSnapshot, ...]) -> list[dict]:
    return [
        {
            "time": int(c.time.timestamp()),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "tick_volume": c.tick_volume,
        }
        for c in snapshot
    ]


def _snapshot_from_json(data: list[dict] | None) -> tuple[CandleSnapshot, ...]:
    if not data:
        return ()
    return tuple(
        CandleSnapshot(
            time=datetime.fromtimestamp(d["time"], tz=UTC),
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            tick_volume=d["tick_volume"],
        )
        for d in data
    )


def _to_row(record: TradeRecord) -> TradeRow:
    return TradeRow(
        id=record.id,
        symbol=record.symbol,
        side=record.side,
        volume=record.volume,
        open_price=record.open_price,
        open_time=int(record.open_time.timestamp()),
        sl=record.sl,
        tp=record.tp,
        spread_points_at_entry=record.spread_points_at_entry,
        comment=record.comment,
        strategy_version=record.strategy_version,
        skill=record.skill,
        close_price=record.close_price,
        close_time=int(record.close_time.timestamp()) if record.close_time else None,
        profit=record.profit,
        m5_entry_snapshot=_snapshot_to_json(record.m5_entry_snapshot),
        h1_entry_snapshot=_snapshot_to_json(record.h1_entry_snapshot),
        m5_exit_snapshot=_snapshot_to_json(record.m5_exit_snapshot),
        h1_exit_snapshot=_snapshot_to_json(record.h1_exit_snapshot),
    )


def _to_domain(row: TradeRow) -> TradeRecord:
    return TradeRecord(
        id=row.id,
        symbol=row.symbol,
        side=row.side,
        volume=row.volume,
        open_price=row.open_price,
        open_time=datetime.fromtimestamp(row.open_time, tz=UTC),
        sl=row.sl,
        tp=row.tp,
        spread_points_at_entry=row.spread_points_at_entry,
        comment=row.comment,
        strategy_version=row.strategy_version,
        skill=row.skill,
        close_price=row.close_price,
        close_time=datetime.fromtimestamp(row.close_time, tz=UTC) if row.close_time else None,
        profit=row.profit,
        m5_entry_snapshot=_snapshot_from_json(row.m5_entry_snapshot),
        h1_entry_snapshot=_snapshot_from_json(row.h1_entry_snapshot),
        m5_exit_snapshot=_snapshot_from_json(row.m5_exit_snapshot),
        h1_exit_snapshot=_snapshot_from_json(row.h1_exit_snapshot),
    )
