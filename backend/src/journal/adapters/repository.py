"""Trade record persistence (sync SQLAlchemy; call via asyncio.to_thread)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.journal.adapters.orm import TradeRow
from src.journal.domain.models import CandleSnapshot, TradeRecord

Outcome = Literal["win", "loss", "breakeven", "open"]
OrderField = Literal["open_time", "close_time", "profit"]
_ORDER_COLUMNS: dict[OrderField, ColumnElement] = {
    "open_time": TradeRow.open_time,
    "close_time": TradeRow.close_time,
    "profit": TradeRow.profit,
}


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

    def search(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        strategy_version: str | None = None,
        skill: str | None = None,
        outcome: Outcome | None = None,
        open_from: int | None = None,
        open_to: int | None = None,
        close_from: int | None = None,
        close_to: int | None = None,
        order_by: OrderField = "open_time",
        order_dir: Literal["asc", "desc"] = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TradeRecord], int]:
        """Filterable, paginated trade history query (any symbol, any field
        combination) — backs `GET /journal/history`."""
        filters: list[ColumnElement] = []
        if symbol is not None:
            filters.append(TradeRow.symbol == symbol)
        if side is not None:
            filters.append(TradeRow.side == side)
        if strategy_version is not None:
            filters.append(TradeRow.strategy_version == strategy_version)
        if skill is not None:
            filters.append(TradeRow.skill == skill)
        if outcome == "open":
            filters.append(TradeRow.close_time.is_(None))
        elif outcome == "win":
            filters.extend([TradeRow.close_time.is_not(None), TradeRow.profit > 0])
        elif outcome == "loss":
            filters.extend([TradeRow.close_time.is_not(None), TradeRow.profit < 0])
        elif outcome == "breakeven":
            filters.extend([TradeRow.close_time.is_not(None), TradeRow.profit == 0])
        if open_from is not None:
            filters.append(TradeRow.open_time >= open_from)
        if open_to is not None:
            filters.append(TradeRow.open_time <= open_to)
        if close_from is not None:
            filters.append(TradeRow.close_time >= close_from)
        if close_to is not None:
            filters.append(TradeRow.close_time <= close_to)

        count_query = select(func.count()).select_from(TradeRow).where(*filters)
        order_column = _ORDER_COLUMNS[order_by]
        order_clause = order_column.desc() if order_dir == "desc" else order_column.asc()
        page_query = (
            select(TradeRow).where(*filters).order_by(order_clause).limit(limit).offset(offset)
        )
        with self._session_factory() as session:
            total = session.scalar(count_query) or 0
            rows = session.scalars(page_query).all()
        return [_to_domain(row) for row in rows], total


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
