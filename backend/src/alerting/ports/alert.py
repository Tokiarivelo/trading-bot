"""Port: notification delivery, provider-agnostic (Telegram, email, ...)."""

from __future__ import annotations

from typing import Protocol

from src.alerting.domain.models import AlertMessage


class AlertPort(Protocol):
    async def send(self, message: AlertMessage) -> None: ...
