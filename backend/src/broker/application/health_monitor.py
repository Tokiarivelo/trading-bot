"""Background gateway-connectivity watchdog (Phase 9 §12, reconnect/resume).

`AccountService.reconnect_from_stored` only ever runs once, at backend
startup (`main.py`'s lifespan) — there was nothing watching for a mid-session
gateway drop and recovery. This fills that gap: polls `account.status()`
periodically, same `start()`/`_run()`/`stop()` background-task shape as
`NewsWindowService`/`CandleStreamService`. On the gateway coming back up
after being down, it re-attempts login from stored credentials and runs a
full position reconciliation (`ReconciliationService.reconcile_all`) —
catching any broker-side close that happened while the backend couldn't see
it. Publishes `GatewayHealthChanged` on any connectivity transition so
`alerting` can notify the operator.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from src.broker.application.account_service import AccountService
from src.broker.application.reconciliation import ReconciliationService
from src.broker.domain.account import BrokerUnavailable
from src.shared.events.bus import EventBus
from src.shared.events.definitions import GatewayHealthChanged

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_S = 20.0


class GatewayHealthMonitor:
    def __init__(
        self,
        account: AccountService,
        reconciliation: ReconciliationService,
        event_bus: EventBus,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._account = account
        self._reconciliation = reconciliation
        self._event_bus = event_bus
        self._poll_interval_s = poll_interval_s
        self._task: asyncio.Task[None] | None = None
        self._last_gateway_up: bool | None = None
        self._last_terminal_connected: bool | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="gateway-health-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await self._check_once()
            await asyncio.sleep(self._poll_interval_s)

    async def _check_once(self) -> None:
        try:
            status = await self._account.status()
        except Exception:
            logger.exception("gateway health check failed")
            return

        gateway_up = bool(status["gateway_up"])
        terminal_connected = bool(status["connected"])
        first_check = self._last_gateway_up is None
        gateway_recovered = not first_check and gateway_up and not self._last_gateway_up
        changed = not first_check and (
            gateway_up != self._last_gateway_up
            or terminal_connected != self._last_terminal_connected
        )
        self._last_gateway_up = gateway_up
        self._last_terminal_connected = terminal_connected

        if first_check:
            # Baseline only — `main.py`'s lifespan already did the
            # startup reconnect + reconciliation pass once.
            return
        if changed:
            await self._event_bus.publish(
                GatewayHealthChanged(gateway_up=gateway_up, terminal_connected=terminal_connected)
            )
        if gateway_recovered:
            logger.info("gateway reconnected — reattempting login and reconciling positions")
            if await self._account.reconnect_from_stored():
                try:
                    await self._reconciliation.reconcile_all()
                except BrokerUnavailable as exc:
                    logger.warning("reconciliation failed after gateway recovery: %s", exc)
