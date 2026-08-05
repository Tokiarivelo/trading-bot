"""Signal-decision persistence (sync SQLAlchemy, same convention as
`repository.py`: the application layer calls these through
`asyncio.to_thread`)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.activity.adapters.orm import SignalDecisionRow
from src.activity.domain.models import SignalDecision

# Once an entry actually filled, nothing may downgrade it: the multi-target
# entry loop can emit a later rejection for TP2 after TP1 already opened, and
# "this signal became a trade" is the answer the chart must keep showing.
_TERMINAL_OUTCOME = "opened"


class SignalDecisionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, decision: SignalDecision) -> None:
        with self._session_factory() as session:
            session.add(
                SignalDecisionRow(
                    signal_id=decision.signal_id,
                    account_id=decision.account_id,
                    bot=decision.bot,
                    strategy=decision.strategy,
                    symbol=decision.symbol,
                    timeframe=decision.timeframe,
                    direction=decision.direction,
                    price=decision.price,
                    created_at=int(decision.created_at.timestamp()),
                    outcome=decision.outcome,
                    reason=decision.reason,
                    confidence=decision.confidence,
                )
            )
            session.commit()

    def set_outcome(self, signal_id: str, outcome: str, *, reason: str | None = None) -> bool:
        """Updates a recorded decision's terminal outcome. Returns whether a
        row was actually changed — `False` both when `signal_id` is unknown
        and when the decision had already reached `opened`."""
        values: dict[str, object] = {"outcome": outcome}
        if reason is not None:
            values["reason"] = reason
        with self._session_factory() as session:
            result = session.execute(
                update(SignalDecisionRow)
                .where(
                    SignalDecisionRow.signal_id == signal_id,
                    SignalDecisionRow.outcome != _TERMINAL_OUTCOME,
                )
                .values(**values)
            )
            session.commit()
            return bool(result.rowcount)

    def list_for_bot(
        self,
        *,
        bot: str,
        account_id: str = "default",
        created_from: int | None = None,
        created_to: int | None = None,
        limit: int = 5000,
    ) -> list[SignalDecision]:
        """This bot's decisions in the window, oldest first — backs the
        chart's signal trail."""
        filters: list[ColumnElement] = [
            SignalDecisionRow.account_id == account_id,
            SignalDecisionRow.bot == bot,
        ]
        if created_from is not None:
            filters.append(SignalDecisionRow.created_at >= created_from)
        if created_to is not None:
            filters.append(SignalDecisionRow.created_at <= created_to)
        query = (
            select(SignalDecisionRow)
            .where(*filters)
            .order_by(SignalDecisionRow.created_at, SignalDecisionRow.id)
            .limit(limit)
        )
        with self._session_factory() as session:
            rows = session.scalars(query).all()
        return [_to_domain(row) for row in rows]

    def earliest_created_at(self, *, account_id: str = "default") -> int | None:
        """Epoch seconds of this account's oldest recorded decision, or `None`
        when the table has none yet. Anything older than this predates the
        table and can only be answered by the legacy log-scrape path (see
        `ActivityLogService.get_bot_signals`)."""
        query = select(func.min(SignalDecisionRow.created_at)).where(
            SignalDecisionRow.account_id == account_id
        )
        with self._session_factory() as session:
            return session.scalar(query)


def _to_domain(row: SignalDecisionRow) -> SignalDecision:
    return SignalDecision(
        signal_id=row.signal_id,
        account_id=row.account_id,
        bot=row.bot,
        strategy=row.strategy,
        symbol=row.symbol,
        timeframe=row.timeframe,
        direction=row.direction,
        price=row.price,
        created_at=datetime.fromtimestamp(row.created_at, tz=UTC),
        outcome=row.outcome,
        reason=row.reason,
        confidence=row.confidence,
    )
