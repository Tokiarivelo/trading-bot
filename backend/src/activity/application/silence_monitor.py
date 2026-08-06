"""Dead-bot silence alerting (OBSERVABILITY_PLAN.md Phase 5): periodically
compares every bot's gap since its last signal against its own median
inter-signal interval, and publishes `BotWentSilent` the moment a bot crosses
that threshold — otherwise a bot that has silently stopped firing (a broken
skill assignment, an exception swallowed upstream, a strategy bug) looks
indistinguishable from "the market is just quiet right now".

Same `start()`/`stop()`/`_run()` background-task shape as
`GatewayHealthMonitor`/`ReconciliationPoller`: one instance per account
(`container.py`), each polling only its own account's `signal_decisions`
rows and publishing onto its own account's event bus.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from src.activity.adapters.signal_decision_repository import SignalDecisionRepository
from src.activity.domain.silence import (
    DEFAULT_SILENCE_MULTIPLIER,
    MIN_SIGNALS_FOR_BASELINE,
    detect_silence,
)
from src.shared.events.bus import EventBus
from src.shared.events.definitions import BotWentSilent
from src.shared.logging.account_context import current_account_id

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_S = 900.0  # 15 min — silence is a slow-moving signal
_DEFAULT_LOOKBACK = timedelta(days=30)


class SilenceMonitor:
    def __init__(
        self,
        signal_decisions: SignalDecisionRepository,
        event_bus: EventBus,
        *,
        account_id: str = "default",
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        lookback: timedelta = _DEFAULT_LOOKBACK,
        multiplier: float = DEFAULT_SILENCE_MULTIPLIER,
        min_signals: int = MIN_SIGNALS_FOR_BASELINE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._signal_decisions = signal_decisions
        self._event_bus = event_bus
        self._account_id = account_id
        self._poll_interval_s = poll_interval_s
        self._lookback = lookback
        self._multiplier = multiplier
        self._min_signals = min_signals
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        # Bots already warned about their *current* silent spell — cleared
        # the moment a bot stops being silent (fired again, or aged out of
        # the lookback window), so a later silent spell can alert again
        # instead of warning about the same bot exactly once forever.
        self._already_alerted: set[str] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="silence-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        current_account_id.set(self._account_id)
        while True:
            await self.check_once()
            await asyncio.sleep(self._poll_interval_s)

    async def check_once(self) -> None:
        now = self._clock()
        try:
            decisions = await asyncio.to_thread(
                self._signal_decisions.list_between,
                account_id=self._account_id,
                created_from=int((now - self._lookback).timestamp()),
            )
        except Exception:
            logger.exception("silence monitor: could not load signal decisions")
            return

        by_bot: dict[str, list[datetime]] = defaultdict(list)
        for decision in decisions:
            by_bot[decision.bot].append(decision.created_at)

        currently_silent: set[str] = set()
        for bot, times in by_bot.items():
            status = detect_silence(
                times, now=now, multiplier=self._multiplier, min_signals=self._min_signals
            )
            if not status.silent:
                continue
            currently_silent.add(bot)
            if bot in self._already_alerted:
                continue  # already warned about this bot's ongoing silence
            self._already_alerted.add(bot)
            logger.warning(
                "bot %s has gone silent: no signal for %.0fs (median interval %.0fs, "
                "threshold %.0fs)",
                bot,
                status.elapsed_s,
                status.median_interval_s or 0.0,
                status.threshold_s or 0.0,
            )
            await self._event_bus.publish(
                BotWentSilent(
                    bot=bot,
                    elapsed_s=status.elapsed_s,
                    median_interval_s=status.median_interval_s or 0.0,
                    threshold_s=status.threshold_s or 0.0,
                    last_signal_at=status.last_signal_at,
                )
            )
        self._already_alerted &= currently_silent
