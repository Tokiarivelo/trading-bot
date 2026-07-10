"""Port: where live market events get pushed (WS clients in production)."""

from __future__ import annotations

from typing import Any, Protocol


class MarketBroadcastPort(Protocol):
    async def broadcast(self, message: dict[str, Any]) -> None: ...
