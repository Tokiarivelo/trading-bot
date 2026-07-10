"""In-process async event bus.

Modules communicate through this bus instead of importing each other:
the engine emits CandleClosed/PositionClosed, the journal emits
TenTradesCompleted, the news module emits NewsWindowEntered, etc.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from src.shared.events.definitions import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = self._handlers.get(type(event), [])
        if not handlers:
            logger.debug("no handlers for %s", type(event).__name__)
            return
        results = await asyncio.gather(
            *(handler(event) for handler in handlers), return_exceptions=True
        )
        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, BaseException):
                # One failing subscriber must never break the others —
                # a journal write error must not stop trade execution.
                logger.exception(
                    "handler %s failed for %s",
                    getattr(handler, "__qualname__", handler),
                    type(event).__name__,
                    exc_info=result,
                )
