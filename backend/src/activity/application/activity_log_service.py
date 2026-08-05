"""Activity log query use case: read-only search over persisted bot logs
(§ "know what it's doing now and why" — see `shared/logging` for how entries
get written)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from src.activity.adapters.repository import ActivityLogRepository
from src.activity.adapters.signal_decision_repository import SignalDecisionRepository
from src.activity.application.bot_signals import extract_bot_signals
from src.activity.domain.funnel import BotFunnel, build_funnels
from src.activity.domain.models import BotSignal, LogEntry, SignalDecision

# How far back to look when the caller doesn't specify a range — bounds the
# query on a potentially large table without requiring every caller to know
# a sensible window.
_DEFAULT_SIGNAL_WINDOW = timedelta(days=14)

# The only loggers a bot's own decision-trail lines (SIGNAL/ENTRY */SIZING OK)
# ever come from — see `activity.application.bot_signals` module docstring.
_SIGNAL_LOGGERS = ("src.engine.application.trade_loop", "src.broker.application.order_service")


class ActivityLogService:
    def __init__(
        self,
        repository: ActivityLogRepository,
        account_id: str = "default",
        signal_decisions: SignalDecisionRepository | None = None,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._signal_decisions = signal_decisions

    async def get_bot_signals(
        self, *, skill: str, created_from: int | None = None, created_to: int | None = None
    ) -> list[BotSignal]:
        """`skill`'s own signal→outcome trail, for the chart overlay.

        Source of truth is the `signal_decisions` table, which the engine
        writes directly (OBSERVABILITY_PLAN.md Phase 1). That table only
        starts at the moment the feature shipped, so the part of the requested
        window that predates its **oldest row** is still answered by the
        legacy log-scrape path (`bot_signals.extract_bot_signals`) — the two
        halves are concatenated at that boundary, never overlapping, so a
        signal can't appear twice. Once the oldest activity log has aged out
        past the table's start (or with no repository wired at all, e.g. in
        tests), the whole answer comes from one path or the other.
        """
        if created_from is None:
            created_from = int((datetime.now(UTC) - _DEFAULT_SIGNAL_WINDOW).timestamp())

        table_start: int | None = None
        typed: list[BotSignal] = []
        if self._signal_decisions is not None:
            table_start = await asyncio.to_thread(
                self._signal_decisions.earliest_created_at, account_id=self._account_id
            )
            if table_start is not None:
                decisions: list[SignalDecision] = await asyncio.to_thread(
                    self._signal_decisions.list_for_bot,
                    bot=skill,
                    account_id=self._account_id,
                    created_from=max(created_from, table_start),
                    created_to=created_to,
                )
                typed = [_to_bot_signal(d) for d in decisions]
                if created_from >= table_start:
                    return typed  # window is entirely covered by the table
                # Legacy half below covers only up to the row before the
                # table's first decision.
                created_to = table_start - 1

        legacy = await self._scrape_bot_signals(
            skill=skill, created_from=created_from, created_to=created_to
        )
        return legacy + typed

    async def get_signal_funnel(
        self,
        *,
        skill: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> list[BotFunnel]:
        """The veto funnel over the window: per bot, how many signals fired
        and how many survived each gate, with the drop reasons
        (OBSERVABILITY_PLAN.md Phase 2).

        Built only from the typed `signal_decisions` table — unlike the signal
        trail there is deliberately **no** legacy log-scrape fallback: the old
        log vocabulary collapsed every risk block into one bucket, which is
        exactly the ambiguity this funnel exists to remove. A window entirely
        predating the table therefore returns an empty funnel rather than a
        misleading one. Defaults to the last 14 days when `created_from` is
        omitted, same as `get_bot_signals`.
        """
        if self._signal_decisions is None:
            return []
        if created_from is None:
            created_from = int((datetime.now(UTC) - _DEFAULT_SIGNAL_WINDOW).timestamp())
        decisions: list[SignalDecision] = await asyncio.to_thread(
            self._signal_decisions.list_between,
            account_id=self._account_id,
            created_from=created_from,
            created_to=created_to,
            bot=skill,
        )
        return build_funnels(decisions)

    async def _scrape_bot_signals(
        self, *, skill: str, created_from: int, created_to: int | None
    ) -> list[BotSignal]:
        """LEGACY read path: reconstructs the trail by regex-parsing the bot's
        own decision-trail log lines. Only used for the window that predates
        the `signal_decisions` table — see `get_bot_signals`."""
        entries: list[LogEntry] = []
        for logger_name in _SIGNAL_LOGGERS:
            rows, _total = await asyncio.to_thread(
                self._repository.search,
                logger_contains=logger_name,
                created_from=created_from,
                created_to=created_to,
                limit=5000,
                account_id=self._account_id,
            )
            entries.extend(rows)
        entries.sort(key=lambda e: (e.created_at, e.id or 0))
        return extract_bot_signals(entries, skill)

    async def search(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[LogEntry], int]:
        return await asyncio.to_thread(
            self._repository.search,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
            account_id=self._account_id,
        )

    async def delete_by_ids(self, ids: list[int]) -> int:
        return await asyncio.to_thread(self._repository.delete_by_ids, ids, self._account_id)

    async def delete_by_filter(
        self,
        *,
        level: str | None = None,
        logger_contains: str | None = None,
        q: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> int:
        return await asyncio.to_thread(
            self._repository.delete_by_filter,
            level=level,
            logger_contains=logger_contains,
            q=q,
            created_from=created_from,
            created_to=created_to,
            account_id=self._account_id,
        )


def _to_bot_signal(decision: SignalDecision) -> BotSignal:
    """Projects a typed `SignalDecision` onto the wire shape the chart already
    consumes — same closed outcome vocabulary, so the frontend's
    `SIGNAL_OUTCOME_META[outcome]` lookup (which is unguarded) keeps working
    whether a row came from the table or the legacy scrape."""
    return BotSignal(
        time=decision.created_at,
        direction=decision.direction,
        outcome=decision.outcome,
        reason=decision.reason,
        price=decision.price,
        checks=decision.checks,
    )
