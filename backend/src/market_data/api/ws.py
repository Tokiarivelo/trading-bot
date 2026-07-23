"""Socket.IO fan-out for live market events (implements MarketBroadcastPort).

Clients join a room per `account_id:symbol:timeframe` (`subscribe`/
`unsubscribe` events) and receive only `candle_closed` events for the rooms
they're in — filtering happens server-side instead of on every client. The
`account_id` segment (MULTI_ACCOUNT_PLAN.md Phase 8) keeps two accounts'
candles for the same broker symbol (e.g. `XAUUSD` on two different brokers)
from colliding in the same room — each account has its own
`CandleStreamService`/`LiveCandleService`/`WsBroadcaster` (see
`container.py`'s `build_account_runtime`), so the room key has to carry the
account through too. Mounted into the ASGI app alongside FastAPI in
`src.main` (Next rewrites don't proxy WS, so the frontend still connects to
the backend directly — see `frontend/src/shared/api/ws.ts`).

Subscribing also tells that account's `CandleStreamService` (via
`bind_candle_stream`, called once per account at startup in `src.main`) to
start polling that symbol if it isn't already part of the engine's
configured universe — otherwise a chart browsing an ad-hoc symbol (see
`SymbolPicker`) would load history once and then sit frozen, never
receiving `candle_closed` events. It also tells that account's
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

# Keyed by account_id — one candle stream / live-candle service per account
# (see `container.py`'s per-account `AccountRuntime`).
_candle_streams: dict[str, CandleStreamService] = {}
_live_candles: dict[str, LiveCandleService] = {}
_session_issuer: SessionTokenIssuer | None = None
_password_getter: Callable[[], str] | None = None
# Rooms each connected client currently has open — needed to unwatch the
# right symbols/rooms on disconnect, since Socket.IO leaves rooms
# automatically but doesn't tell us what to release on our side.
_sid_symbols: dict[str, set[tuple[str, str]]] = {}
_sid_rooms: dict[str, set[tuple[str, str, Timeframe]]] = {}


def bind_candle_stream(account_id: str, candle_stream: CandleStreamService) -> None:
    """Wire one account's candle stream service so subscribe/unsubscribe can
    extend its active symbol set. Called once per enabled account from
    `src.main`'s lifespan, after the container is built."""
    _candle_streams[account_id] = candle_stream


def bind_live_candle(account_id: str, live_candle: LiveCandleService) -> None:
    """Wire one account's live-candle preview service so subscribe/
    unsubscribe can start/stop streaming a room's in-progress bar. Called
    once per enabled account from `src.main`'s lifespan, after the container
    is built."""
    _live_candles[account_id] = live_candle


def bind_auth(session_issuer: SessionTokenIssuer, password_getter: Callable[[], str]) -> None:
    """Wire session verification so `connect` can require the same app
    password as every REST route (§11). Called once from `src.main`'s
    lifespan, after the container is built."""
    global _session_issuer, _password_getter
    _session_issuer = session_issuer
    _password_getter = password_getter


def _room(account_id: str, symbol: str, timeframe: str) -> str:
    return f"{account_id}:{symbol}:{timeframe}"


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
    if symbols:
        for account_id, symbol in symbols:
            candle_stream = _candle_streams.get(account_id)
            if candle_stream is not None:
                candle_stream.unwatch(symbol)
    rooms = _sid_rooms.pop(sid, None)
    if rooms:
        for account_id, symbol, timeframe in rooms:
            live_candle = _live_candles.get(account_id)
            if live_candle is not None:
                live_candle.unwatch(symbol, timeframe)


@sio.on("subscribe")
async def subscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `subscribe`.

    Payload: `{"account_id": str, "symbol": str, "timeframe": "M1" | "M5" |
    "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN"}`.
    Joins the `<account_id>:<symbol>:<timeframe>` room; the client starts
    receiving that room's `candle_closed` and `candle_update` events. Also
    starts that account's candle stream polling `symbol` if it wasn't
    already covered by `configs/app.yaml: symbols`, and starts that
    account's live-candle preview streaming this room's in-progress bar
    every ~1.5s. An unknown `account_id` (not in `configs/accounts.yaml`, or
    disabled) joins the room harmlessly but never receives events, since no
    candle stream ever broadcasts into it. No acknowledgement is emitted.
    """
    account_id = data["account_id"]
    symbol = data["symbol"]
    timeframe = Timeframe(data["timeframe"])
    room = _room(account_id, symbol, timeframe.value)
    await sio.enter_room(sid, room)

    sid_symbols = _sid_symbols.setdefault(sid, set())
    symbol_key = (account_id, symbol)
    if symbol_key not in sid_symbols:
        sid_symbols.add(symbol_key)
        candle_stream = _candle_streams.get(account_id)
        if candle_stream is not None:
            candle_stream.watch(symbol)

    sid_rooms = _sid_rooms.setdefault(sid, set())
    room_key = (account_id, symbol, timeframe)
    if room_key not in sid_rooms:
        sid_rooms.add(room_key)
        live_candle = _live_candles.get(account_id)
        if live_candle is not None:
            live_candle.watch(symbol, timeframe)


@sio.on("unsubscribe")
async def unsubscribe(sid: str, data: dict[str, str]) -> None:
    """Client -> server event `unsubscribe`.

    Payload: `{"account_id": str, "symbol": str, "timeframe": "M1" | "M5" |
    "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN"}`.
    Leaves the `<account_id>:<symbol>:<timeframe>` room, stops that
    account's live-candle preview for it, and stops that account's candle
    stream from polling `symbol` once no client has any room open for it
    anymore (unless it's part of the engine's configured universe, which
    always stays live).
    """
    account_id = data["account_id"]
    symbol = data["symbol"]
    timeframe = Timeframe(data["timeframe"])
    room = _room(account_id, symbol, timeframe.value)
    await sio.leave_room(sid, room)

    sid_symbols = _sid_symbols.get(sid)
    symbol_key = (account_id, symbol)
    if sid_symbols and symbol_key in sid_symbols:
        sid_symbols.discard(symbol_key)
        candle_stream = _candle_streams.get(account_id)
        if candle_stream is not None:
            candle_stream.unwatch(symbol)

    sid_rooms = _sid_rooms.get(sid)
    room_key = (account_id, symbol, timeframe)
    if sid_rooms and room_key in sid_rooms:
        sid_rooms.discard(room_key)
        live_candle = _live_candles.get(account_id)
        if live_candle is not None:
            live_candle.unwatch(symbol, timeframe)


class WsBroadcaster:
    """Implements `market_data.ports.MarketBroadcastPort` over Socket.IO.

    One instance per account (see `container.py`'s `build_account_runtime`)
    — `account_id` scopes every emit to that account's own room so two
    accounts' candles for the same broker symbol never collide."""

    def __init__(self, account_id: str) -> None:
        self._account_id = account_id

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Server -> client event `candle_closed`, emitted to the
        `<account_id>:<symbol>:<timeframe>` room only.

        `message` shape: `{"type": "candle_closed", "candle": CandleOut}` —
        see `market_data.api.schemas.CandleOut` for the candle fields.
        """
        candle = message["candle"]
        room = _room(self._account_id, candle["symbol"], candle["timeframe"])
        await sio.emit(message["type"], message, room=room)
