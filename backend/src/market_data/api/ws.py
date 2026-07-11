"""Socket.IO fan-out for live market events (implements MarketBroadcastPort).

Clients join a room per `symbol:timeframe` (`subscribe`/`unsubscribe` events)
and receive only `candle_closed` events for the rooms they're in — filtering
happens server-side instead of on every client. Mounted into the ASGI app
alongside FastAPI in `src.main` (Next rewrites don't proxy WS, so the
frontend still connects to the backend directly — see
`frontend/src/shared/api/ws.ts`).
"""

from __future__ import annotations

import logging
from typing import Any

import socketio

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


def _room(symbol: str, timeframe: str) -> str:
    return f"{symbol}:{timeframe}"


@sio.event
async def connect(sid: str, _environ: dict[str, Any]) -> None:
    """Built-in Socket.IO lifecycle event — fires on every new client connection."""
    logger.info("ws client connected sid=%s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    """Built-in Socket.IO lifecycle event — fires on disconnect; rooms are
    left automatically, no explicit cleanup needed."""
    logger.info("ws client disconnected sid=%s", sid)


@sio.on("subscribe")
async def subscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `subscribe`.

    Payload: `{"symbol": str, "timeframe": "M5" | "H1" | "H4" | "D1"}`.
    Joins the `<symbol>:<timeframe>` room; the client starts receiving that
    room's `candle_closed` events. No acknowledgement is emitted.
    """
    room = _room(data["symbol"], data["timeframe"])
    await sio.enter_room(sid, room)


@sio.on("unsubscribe")
async def unsubscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `unsubscribe`.

    Payload: `{"symbol": str, "timeframe": "M5" | "H1" | "H4" | "D1"}`.
    Leaves the `<symbol>:<timeframe>` room.
    """
    room = _room(data["symbol"], data["timeframe"])
    await sio.leave_room(sid, room)


class WsBroadcaster:
    """Implements `market_data.ports.MarketBroadcastPort` over Socket.IO."""

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Server -> client event `candle_closed`, emitted to the
        `<symbol>:<timeframe>` room only.

        `message` shape: `{"type": "candle_closed", "candle": CandleOut}` —
        see `market_data.api.schemas.CandleOut` for the candle fields.
        """
        candle = message["candle"]
        room = _room(candle["symbol"], candle["timeframe"])
        await sio.emit(message["type"], message, room=room)
