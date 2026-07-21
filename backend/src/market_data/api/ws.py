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
then sit frozen, never receiving `candle_closed` events. It also tells the
`LiveCandleService` (via `bind_live_candle`) to start streaming that room's
in-progress bar every ~1.5s as `candle_update` events, so the rightmost
candle moves continuously like MT5 instead of waiting for the whole bar to
close.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import socketio

from src.market_data.domain.models import Timeframe
from src.shared.auth.dependencies import SESSION_TTL_SECONDS

if TYPE_CHECKING:
    from src.market_data.application.candle_stream import CandleStreamService
    from src.market_data.application.live_candle import LiveCandleService
    from src.shared.auth.session import SessionTokenIssuer

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

_candle_stream: CandleStreamService | None = None
_live_candle: LiveCandleService | None = None
_session_issuer: SessionTokenIssuer | None = None
_password_getter: Callable[[], str] | None = None
# Rooms each connected client currently has open — needed to unwatch the
# right symbols/rooms on disconnect, since Socket.IO leaves rooms
# automatically but doesn't tell us what to release on our side.
_sid_symbols: dict[str, set[str]] = {}
_sid_rooms: dict[str, set[tuple[str, Timeframe]]] = {}


def bind_candle_stream(candle_stream: CandleStreamService) -> None:
    """Wire the candle stream service so subscribe/unsubscribe can extend its
    active symbol set. Called once from `src.main`'s lifespan, after the
    container is built."""
    global _candle_stream
    _candle_stream = candle_stream


def bind_live_candle(live_candle: LiveCandleService) -> None:
    """Wire the live-candle preview service so subscribe/unsubscribe can
    start/stop streaming a room's in-progress bar. Called once from
    `src.main`'s lifespan, after the container is built."""
    global _live_candle
    _live_candle = live_candle


def bind_auth(session_issuer: SessionTokenIssuer, password_getter: Callable[[], str]) -> None:
    """Wire session verification so `connect` can require the same app
    password as every REST route (§11). Called once from `src.main`'s
    lifespan, after the container is built."""
    global _session_issuer, _password_getter
    _session_issuer = session_issuer
    _password_getter = password_getter


def _room(symbol: str, timeframe: str) -> str:
    return f"{symbol}:{timeframe}"


@sio.event
async def connect(sid: str, _environ: dict[str, Any], auth: dict[str, Any] | None = None) -> None:
    """Built-in Socket.IO lifecycle event — fires on every new client
    connection. `auth` is whatever the client passed as its handshake `auth`
    payload (see `frontend/src/shared/api/ws.ts`); required to be a valid
    session token when an app password is configured (§11), same guard as
    every REST route (`shared/auth/dependencies.py: require_session`)."""
    password = _password_getter() if _password_getter else ""
    if password:
        token = (auth or {}).get("token", "")
        # verify() hits the OS keyring synchronously — offload it so a slow/
        # unresponsive keyring backend can't stall the event loop for every
        # other connection and request.
        valid = _session_issuer is not None and await asyncio.to_thread(
            _session_issuer.verify, token, SESSION_TTL_SECONDS
        )
        if not valid:
            logger.warning("ws client rejected: missing/invalid session sid=%s", sid)
            raise ConnectionRefusedError("authentication required")
    logger.info("ws client connected sid=%s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    """Built-in Socket.IO lifecycle event — fires on disconnect; rooms are
    left automatically, but the candle stream's ad-hoc watch lists are ours
    to release explicitly."""
    logger.info("ws client disconnected sid=%s", sid)
    symbols = _sid_symbols.pop(sid, None)
    if symbols and _candle_stream is not None:
        for symbol in symbols:
            _candle_stream.unwatch(symbol)
    rooms = _sid_rooms.pop(sid, None)
    if rooms and _live_candle is not None:
        for symbol, timeframe in rooms:
            _live_candle.unwatch(symbol, timeframe)


@sio.on("subscribe")
async def subscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `subscribe`.

    Payload: `{"symbol": str, "timeframe": "M1" | "M5" | "M15" | "M30" | "H1" |
    "H4" | "D1" | "W1" | "MN"}`.
    Joins the `<symbol>:<timeframe>` room; the client starts receiving that
    room's `candle_closed` and `candle_update` events. Also starts the
    candle stream polling `symbol` if it wasn't already covered by
    `configs/app.yaml: symbols`, and starts the live-candle preview
    streaming this room's in-progress bar every ~1.5s. No acknowledgement is
    emitted.
    """
    symbol = data["symbol"]
    timeframe = Timeframe(data["timeframe"])
    room = _room(symbol, timeframe.value)
    await sio.enter_room(sid, room)

    sid_symbols = _sid_symbols.setdefault(sid, set())
    if symbol not in sid_symbols:
        sid_symbols.add(symbol)
        if _candle_stream is not None:
            _candle_stream.watch(symbol)

    sid_rooms = _sid_rooms.setdefault(sid, set())
    room_key = (symbol, timeframe)
    if room_key not in sid_rooms:
        sid_rooms.add(room_key)
        if _live_candle is not None:
            _live_candle.watch(symbol, timeframe)


@sio.on("unsubscribe")
async def unsubscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `unsubscribe`.

    Payload: `{"symbol": str, "timeframe": "M1" | "M5" | "M15" | "M30" | "H1" |
    "H4" | "D1" | "W1" | "MN"}`.
    Leaves the `<symbol>:<timeframe>` room, stops the live-candle preview
    for it, and stops the candle stream from polling `symbol` once no
    client has any room open for it anymore (unless it's part of the
    engine's configured universe, which always stays live).
    """
    symbol = data["symbol"]
    timeframe = Timeframe(data["timeframe"])
    room = _room(symbol, timeframe.value)
    await sio.leave_room(sid, room)

    sid_symbols = _sid_symbols.get(sid)
    if sid_symbols and symbol in sid_symbols:
        sid_symbols.discard(symbol)
        if _candle_stream is not None:
            _candle_stream.unwatch(symbol)

    sid_rooms = _sid_rooms.get(sid)
    room_key = (symbol, timeframe)
    if sid_rooms and room_key in sid_rooms:
        sid_rooms.discard(room_key)
        if _live_candle is not None:
            _live_candle.unwatch(symbol, timeframe)


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
