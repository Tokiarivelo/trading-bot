/**
 * Socket.IO client for live market events.
 *
 * Next.js rewrites only proxy HTTP, not WebSockets, so this connects to the
 * backend directly. Configure NEXT_PUBLIC_WS_URL when the backend is not on
 * the default dev address. One socket is shared across subscriptions;
 * reconnection (with backoff) is handled by socket.io-client itself, but
 * room membership is server-side state that a reconnect doesn't restore —
 * so this module re-emits `subscribe` for every still-active room on each
 * `connect` (including reconnects), otherwise a chart would silently stop
 * receiving `candle_closed` events after any network blip or backend
 * restart until the user changed symbol/timeframe.
 *
 * The server puts each connection into a room per `symbol:timeframe`
 * (`subscribe`/`unsubscribe` events) and only emits events for the rooms a
 * client is in — see `backend/src/market_data/api/ws.py`.
 */

import { io, type Socket } from "socket.io-client";
import { getToken } from "@/shared/api/client";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "http://127.0.0.1:8000";

let socket: Socket | null = null;
// Rooms currently wanted by at least one subscribeRoom() caller, re-sent to
// the server on every `connect` event (initial connect + every reconnect).
const activeRooms = new Map<string, { symbol: string; timeframe: string }>();

function roomKey(room: { symbol: string; timeframe: string }): string {
  return `${room.symbol}:${room.timeframe}`;
}

function getSocket(): Socket {
  if (!socket) {
    // Sent as the Socket.IO handshake `auth` payload — the server checks it
    // the same way REST routes check `Authorization: Bearer` (§11), since
    // this connection goes straight to the backend and never passes through
    // the Next.js /api rewrite that attaches the header for REST calls.
    socket = io(WS_BASE, { autoConnect: true, reconnection: true, auth: { token: getToken() } });
    socket.on("connect", () => {
      for (const room of activeRooms.values()) socket?.emit("subscribe", room);
    });
  }
  return socket;
}

/** Call after login (or logout) so the next connect/reconnect carries the
 * current token — the socket normally stays open for the app's lifetime, so
 * a fresh login needs to push its new token in rather than wait for a
 * reconnect that may never happen. */
export function refreshWsAuth(): void {
  if (!socket) return;
  socket.auth = { token: getToken() };
  if (socket.connected) socket.disconnect().connect();
}

export type WsHandler = (message: unknown) => void;

/** Fires `handler` on every Socket.IO `connect` event, including reconnects
 * after a network blip or backend restart (not just the initial connect) —
 * `subscribeRoom`'s own `connect` handler above only restores room
 * membership, so callers that need to know "we just reconnected, our data
 * may now have a hole" (e.g. to refetch/patch chart history) hook this
 * instead of re-deriving reconnect detection themselves. Returns an
 * unsubscribe fn. */
export function onSocketConnect(handler: () => void): () => void {
  const s = getSocket();
  s.on('connect', handler);
  return () => {
    s.off('connect', handler);
  };
}

/** Subscribe to one symbol/timeframe room for one or more event names; returns an unsubscribe fn. */
export function subscribeRoom(
  events: string | string[],
  room: { symbol: string; timeframe: string },
  onMessage: WsHandler,
): () => void {
  const s = getSocket();
  const eventNames = Array.isArray(events) ? events : [events];
  const handler = (payload: unknown) => onMessage(payload);
  const key = roomKey(room);

  activeRooms.set(key, room);
  s.emit("subscribe", room);
  for (const event of eventNames) s.on(event, handler);

  return () => {
    for (const event of eventNames) s.off(event, handler);
    activeRooms.delete(key);
    s.emit("unsubscribe", room);
  };
}
