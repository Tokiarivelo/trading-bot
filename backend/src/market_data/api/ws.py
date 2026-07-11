"""Socket.IO fan-out for live market events (implements MarketBroadcastPort).

Clients join a room per `symbol:timeframe` (`subscribe`/`unsubscribe` events)
and receive only `candle_closed` events for the rooms they're in — filtering
happens server-side instead of on every client. Mounted into the ASGI app
alongside FastAPI in `src.main` (Next rewrites don't proxy WS, so the
frontend still connects to the backend directly — see
`frontend/src/shared/api/ws.ts`).

Subscribing also tells the `CandleStreamService` (via `bind_candle_stream`,
called once at startup in `src.main`) to start polling that symbol if it
isn't already part of the engine's configured universe — otherwise a chart
browsing an ad-hoc symbol (see `SymbolPicker`) would load history once and
then sit frozen, never receiving `candle_closed` events.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import socketio

if TYPE_CHECKING:
    from src.market_data.application.candle_stream import CandleStreamService

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

_candle_stream: CandleStreamService | None = None
# Symbols each connected client currently has at least one room open for —
# needed to unwatch the right symbols on disconnect, since Socket.IO leaves
# rooms automatically but doesn't tell us what to release on our side.
_sid_symbols: dict[str, set[str]] = {}


def bind_candle_stream(candle_stream: CandleStreamService) -> None:
    """Wire the candle stream service so subscribe/unsubscribe can extend its
    active symbol set. Called once from `src.main`'s lifespan, after the
    container is built."""
    global _candle_stream
    _candle_stream = candle_stream


def _room(symbol: str, timeframe: str) -> str:
    return f"{symbol}:{timeframe}"


@sio.event
async def connect(sid: str, _environ: dict[str, Any]) -> None:
    """Built-in Socket.IO lifecycle event — fires on every new client connection."""
    logger.info("ws client connected sid=%s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    """Built-in Socket.IO lifecycle event — fires on disconnect; rooms are
    left automatically, but the candle stream's ad-hoc watch list is ours to
    release explicitly."""
    logger.info("ws client disconnected sid=%s", sid)
    symbols = _sid_symbols.pop(sid, None)
    if symbols and _candle_stream is not None:
        for symbol in symbols:
            _candle_stream.unwatch(symbol)


@sio.on("subscribe")
async def subscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `subscribe`.

    Payload: `{"symbol": str, "timeframe": "M1" | "M5" | "H1" | "H4" | "D1"}`.
    Joins the `<symbol>:<timeframe>` room; the client starts receiving that
    room's `candle_closed` events. Also starts the candle stream polling
    `symbol` if it wasn't already covered by `configs/app.yaml: symbols`. No
    acknowledgement is emitted.
    """
    symbol = data["symbol"]
    room = _room(symbol, data["timeframe"])
    await sio.enter_room(sid, room)
    sid_symbols = _sid_symbols.setdefault(sid, set())
    if symbol not in sid_symbols:
        sid_symbols.add(symbol)
        if _candle_stream is not None:
            _candle_stream.watch(symbol)


@sio.on("unsubscribe")
async def unsubscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `unsubscribe`.

    Payload: `{"symbol": str, "timeframe": "M1" | "M5" | "H1" | "H4" | "D1"}`.
    Leaves the `<symbol>:<timeframe>` room, and stops the candle stream from
    polling `symbol` once no client has any room open for it anymore (unless
    it's part of the engine's configured universe, which always stays live).
    """
    symbol = data["symbol"]
    room = _room(symbol, data["timeframe"])
    await sio.leave_room(sid, room)
    sid_symbols = _sid_symbols.get(sid)
    if sid_symbols and symbol in sid_symbols:
        sid_symbols.discard(symbol)
        if _candle_stream is not None:
            _candle_stream.unwatch(symbol)


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
