"""Signal-decision write use case — the `SignalDecisionSinkPort`
implementation the engine and the order service write through.

Stamps the account this runtime belongs to and pushes the sync repository
call onto a thread, exactly like `ActivityLogService` does for reads. Write
failures are logged and swallowed: the decision trail is observability, and
losing a row must never abort a live entry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from src.activity.adapters.signal_decision_repository import SignalDecisionRepository
from src.activity.domain.models import DecisionCheck, SignalDecision

logger = logging.getLogger(__name__)

# What a decision carries until a terminal outcome lands — same value the
# legacy log-scraper used for "no outcome line followed".
PENDING_OUTCOME = "skipped"


class SignalDecisionService:
    def __init__(
        self, repository: SignalDecisionRepository, account_id: str = "default"
    ) -> None:
        self._repository = repository
        self._account_id = account_id

    async def record(
        self,
        *,
        signal_id: str,
        bot: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        direction: str,
        price: float | None,
        created_at: datetime,
        reason: str,
        confidence: float | None,
    ) -> None:
        decision = SignalDecision(
            signal_id=signal_id,
            account_id=self._account_id,
            bot=bot,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            price=price,
            created_at=created_at,
            outcome=PENDING_OUTCOME,
            reason=reason,
            confidence=confidence,
        )
        try:
            await asyncio.to_thread(self._repository.save, decision)
        except Exception:
            logger.exception("could not record signal decision signal_id=%s", signal_id)

    async def record_outcome(
        self,
        signal_id: str,
        outcome: str,
        *,
        reason: str | None = None,
        checks: tuple[DecisionCheck, ...] = (),
    ) -> None:
        try:
            await asyncio.to_thread(
                self._repository.set_outcome, signal_id, outcome, reason=reason, checks=checks
            )
        except Exception:
            logger.exception(
                "could not record signal outcome signal_id=%s outcome=%s", signal_id, outcome
            )

    async def record_checks(self, signal_id: str, checks: tuple[DecisionCheck, ...]) -> None:
        if not checks:
            return
        try:
            await asyncio.to_thread(self._repository.append_checks, signal_id, checks)
        except Exception:
            logger.exception("could not record signal checks signal_id=%s", signal_id)
