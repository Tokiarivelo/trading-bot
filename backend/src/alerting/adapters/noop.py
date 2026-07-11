"""AlertPort adapter used when no channel is configured."""

from __future__ import annotations

from src.alerting.domain.models import AlertMessage


class NoopAlertAdapter:
    async def send(self, message: AlertMessage) -> None:
        return None
