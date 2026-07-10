"""WebSocket fan-out for live market events (implements MarketBroadcastPort).

Clients connect to /ws/market-data and receive every candle_closed message;
filtering by symbol/timeframe is client-side (3 symbols × 4 timeframes is
tiny traffic).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WsBroadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        logger.info("ws client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for websocket in list(self._connections):
            try:
                await websocket.send_json(message)
            except Exception:
                # Dead sockets get dropped; their reader task cleans up too.
                self._connections.discard(websocket)
