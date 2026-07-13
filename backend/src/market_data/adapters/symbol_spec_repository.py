"""Persistence for per-symbol broker facts (sync SQLAlchemy; call via
asyncio.to_thread) — see `orm.SymbolSpecRow` for what's stored and why."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from src.market_data.adapters.orm import SymbolSpecRow
from src.market_data.adapters.replay import SymbolSpec


class SymbolSpecRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert(self, symbol: str, spec: SymbolSpec) -> None:
        row = {
            "symbol": symbol,
            "point": spec.point,
            "digits": spec.digits,
            "stops_level": spec.stops_level,
            "contract_size": spec.contract_size,
            "volume_min": spec.volume_min,
            "volume_max": spec.volume_max,
            "volume_step": spec.volume_step,
            "updated_at": int(datetime.now(UTC).timestamp()),
        }
        # SQLite-dialect upsert; swap for postgresql.insert when the DB moves.
        statement = insert(SymbolSpecRow)
        statement = statement.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                col: statement.excluded[col]
                for col in (
                    "point",
                    "digits",
                    "stops_level",
                    "contract_size",
                    "volume_min",
                    "volume_max",
                    "volume_step",
                    "updated_at",
                )
            },
        )
        with self._session_factory() as session:
            session.execute(statement, [row])
            session.commit()

    def get(self, symbol: str) -> SymbolSpec | None:
        query = select(SymbolSpecRow).where(SymbolSpecRow.symbol == symbol)
        with self._session_factory() as session:
            row = session.scalars(query).one_or_none()
        if row is None:
            return None
        return SymbolSpec(
            point=row.point,
            digits=row.digits,
            stops_level=row.stops_level,
            contract_size=row.contract_size,
            volume_min=row.volume_min,
            volume_max=row.volume_max,
            volume_step=row.volume_step,
        )
