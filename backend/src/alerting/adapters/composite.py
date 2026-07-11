"""AlertPort adapter that fans out to every configured channel.

Each adapter already swallows its own errors, but `return_exceptions=True`
here too — one broken channel must never stop another from delivering.
"""

from __future__ import annotations

import asyncio
import logging

from src.alerting.domain.models import AlertMessage
from src.alerting.ports.alert import AlertPort

logger = logging.getLogger(__name__)


class CompositeAlertAdapter:
    def __init__(self, adapters: list[AlertPort]) -> None:
        self._adapters = adapters

    async def send(self, message: AlertMessage) -> None:
        results = await asyncio.gather(
            *(adapter.send(message) for adapter in self._adapters), return_exceptions=True
        )
        for adapter, result in zip(self._adapters, results, strict=True):
            if isinstance(result, BaseException):
                logger.exception(
                    "alert adapter %s failed for %s",
                    type(adapter).__name__,
                    message.title,
                    exc_info=result,
                )
