"""Turns trading events into notifications (Phase 9): fills, circuit
breakers, AI refinements, and gateway connectivity changes. Subscribes to
the event bus rather than being called directly — see `container.py`.
"""

from __future__ import annotations

from src.alerting.domain.models import AlertingConfig, AlertLevel, AlertMessage
from src.alerting.ports.alert import AlertPort
from src.shared.events.definitions import (
    CircuitBreakerTripped,
    GatewayHealthChanged,
    PositionClosed,
    PositionOpened,
    RefinementCompleted,
)


class AlertService:
    def __init__(self, port: AlertPort, config: AlertingConfig) -> None:
        self._port = port
        self._config = config

    async def on_position_opened(self, event: PositionOpened) -> None:
        if not self._config.events.fills:
            return
        await self._port.send(
            AlertMessage(
                title=f"Opened {event.side.upper()} {event.symbol}",
                body=f"{event.volume:.2f} lots @ {event.price:.5f} "
                f"sl={event.sl} tp={event.tp} skill={event.skill or '-'}",
            )
        )

    async def on_position_closed(self, event: PositionClosed) -> None:
        if not self._config.events.fills:
            return
        level = AlertLevel.WARNING if event.profit < 0 else AlertLevel.INFO
        await self._port.send(
            AlertMessage(
                title=f"Closed {event.symbol}",
                body=f"@ {event.close_price:.5f} profit={event.profit:.2f}",
                level=level,
            )
        )

    async def on_circuit_breaker_tripped(self, event: CircuitBreakerTripped) -> None:
        if not self._config.events.circuit_breaker:
            return
        await self._port.send(
            AlertMessage(
                title="Engine paused",
                body=event.reason,
                level=AlertLevel.CRITICAL,
            )
        )

    async def on_refinement_completed(self, event: RefinementCompleted) -> None:
        if not self._config.events.refinements:
            return
        body = f"verdict={event.verdict}"
        if event.proposal_id:
            body += f" proposal={event.proposal_id}"
        await self._port.send(AlertMessage(title=f"AI review completed: {event.symbol}", body=body))

    async def on_gateway_health_changed(self, event: GatewayHealthChanged) -> None:
        if not self._config.events.gateway_disconnect:
            return
        if event.gateway_up and event.terminal_connected:
            await self._port.send(
                AlertMessage(title="Gateway reconnected", body="MT5 terminal connected again.")
            )
        else:
            body = f"gateway_up={event.gateway_up} terminal_connected={event.terminal_connected}"
            await self._port.send(
                AlertMessage(title="Gateway disconnected", body=body, level=AlertLevel.CRITICAL)
            )
