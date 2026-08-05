"""Fast steady-state position reconciliation (§12 follow-up).

`PositionManager.on_candle_closed` only reconciles vanished tickets on the
engine's own `entry_timeframe` candle close (M5 by default) — so a
server-side SL/TP fill sat undetected, and therefore invisible in trade
history/analytics, for up to that whole candle period. This runs
`ReconciliationService.reconcile_all()` on its own short timer instead,
decoupled from candle events entirely, same `start()`/`_run()`/`stop()`
background-task shape as `WalCheckpointService`/`GatewayHealthMonitor`.

`reconcile_all()` is cheap per tick (one `broker.get_positions()` call plus,
only for trades that actually vanished, one `get_close_info()` each) and
already tolerates `BrokerUnavailable` internally; `_close_from_history`'s
journal re-check (see `reconciliation.py`) makes it safe to run alongside
`reconcile_vanished()` without double-publishing `PositionClosed`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from src.broker.application.reconciliation import ReconciliationService
from src.shared.logging.account_context import current_account_id

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_S = 5.0


class ReconciliationPoller:
    def __init__(
        self,
        reconciliation: ReconciliationService,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
        account_id: str = "default",
    ) -> None:
        self._reconciliation = reconciliation
        self._poll_interval_s = poll_interval_s
        self._account_id = account_id
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="reconciliation-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        current_account_id.set(self._account_id)
        while True:
            await self.poll_once()
            await asyncio.sleep(self._poll_interval_s)

    async def poll_once(self) -> None:
        try:
            await self._reconciliation.reconcile_all()
        except Exception:
            logger.exception("reconciliation poll failed")
