"""Signal-decision persistence (sync SQLAlchemy, same convention as
`repository.py`: the application layer calls these through
`asyncio.to_thread`)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.activity.adapters.orm import SignalDecisionRow
from src.activity.domain.models import DecisionCheck, SignalDecision

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
                    checks=_encode_checks(decision.checks),
                    regime_volatility=decision.regime_volatility,
                    regime_volatility_percentile=decision.regime_volatility_percentile,
                    regime_trend=decision.regime_trend,
                    regime_adx=decision.regime_adx,
                    regime_session=decision.regime_session,
                )
            )
            session.commit()

    def set_outcome(
        self,
        signal_id: str,
        outcome: str,
        *,
        reason: str | None = None,
        checks: tuple[DecisionCheck, ...] = (),
    ) -> bool:
        """Updates a recorded decision's terminal outcome. Returns whether a
        row was actually changed — `False` both when `signal_id` is unknown
        and when the decision had already reached `opened`.

        `checks` are **appended** to whatever the row already carries (the
        gates are evaluated one at a time, each stamping only its own), which
        is why this can't be expressed as a bare `UPDATE ... SET checks=`.
        """
        with self._session_factory() as session:
            if checks:
                row = session.scalars(
                    select(SignalDecisionRow).where(SignalDecisionRow.signal_id == signal_id)
                ).one_or_none()
                if row is None:
                    return False
                existing = list(row.checks or [])
                new_checks = _encode_checks(checks)
                # An engine retry (e.g. a second target on the same signal)
                # re-evaluates the same gates; don't let the list grow
                # unboundedly with identical entries.
                row.checks = existing + [c for c in new_checks if c not in existing]
                if row.outcome == _TERMINAL_OUTCOME:
                    session.commit()
                    return False
                row.outcome = outcome
                if reason is not None:
                    row.reason = reason
                session.commit()
                return True

            values: dict[str, object] = {"outcome": outcome}
            if reason is not None:
                values["reason"] = reason
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

    def append_checks(self, signal_id: str, checks: tuple[DecisionCheck, ...]) -> bool:
        """Adds gate checks to a recorded decision without touching its
        outcome — how a *passing* gate records the numbers it saw. Returns
        whether the row existed."""
        if not checks:
            return False
        with self._session_factory() as session:
            row = session.scalars(
                select(SignalDecisionRow).where(SignalDecisionRow.signal_id == signal_id)
            ).one_or_none()
            if row is None:
                return False
            existing = list(row.checks or [])
            row.checks = existing + [c for c in _encode_checks(checks) if c not in existing]
            session.commit()
            return True

    def list_between(
        self,
        *,
        account_id: str = "default",
        created_from: int | None = None,
        created_to: int | None = None,
        bot: str | None = None,
        limit: int = 20000,
    ) -> list[SignalDecision]:
        """Every bot's decisions in the window (or just `bot`'s), oldest
        first — backs the veto funnel aggregation, which needs all bots at
        once rather than one bot's trail."""
        filters: list[ColumnElement] = [SignalDecisionRow.account_id == account_id]
        if bot is not None:
            filters.append(SignalDecisionRow.bot == bot)
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


def _encode_checks(checks: tuple[DecisionCheck, ...]) -> list[list]:
    return [[c.name, c.value, c.threshold, c.comparison, c.passed] for c in checks]


def _decode_checks(raw: list | None) -> tuple[DecisionCheck, ...]:
    """Rows written before Phase 2 have `None`/`[]`; a malformed entry is
    skipped rather than breaking the whole trail read."""
    decoded: list[DecisionCheck] = []
    for entry in raw or []:
        if not isinstance(entry, (list, tuple)) or len(entry) != 5:
            continue
        name, value, threshold, comparison, passed = entry
        decoded.append(
            DecisionCheck(
                name=str(name),
                value=float(value),
                threshold=float(threshold),
                comparison=str(comparison),
                passed=bool(passed),
            )
        )
    return tuple(decoded)


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
        checks=_decode_checks(row.checks),
        regime_volatility=row.regime_volatility,
        regime_volatility_percentile=row.regime_volatility_percentile,
        regime_trend=row.regime_trend,
        regime_adx=row.regime_adx,
        regime_session=row.regime_session,
    )
