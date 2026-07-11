/**
 * Socket.IO client for live market events.
 *
 * Next.js rewrites only proxy HTTP, not WebSockets, so this connects to the
 * backend directly. Configure NEXT_PUBLIC_WS_URL when the backend is not on
 * the default dev address. One socket is shared across subscriptions;
 * reconnection (with backoff) is handled by socket.io-client itself.
 *
 * The server puts each connection into a room per `symbol:timeframe`
 * (`subscribe`/`unsubscribe` events) and only emits events for the rooms a
 * client is in — see `backend/src/market_data/api/ws.py`.
 */

import { io, type Socket } from "socket.io-client";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "http://127.0.0.1:8000";

let socket: Socket | null = null;

function getSocket(): Socket {
  socket ??= io(WS_BASE, { autoConnect: true, reconnection: true });
  return socket;
}

export type WsHandler = (message: unknown) => void;

/** Subscribe to one symbol/timeframe room and a single event name; returns an unsubscribe fn. */
export function subscribeRoom(
  event: string,
  room: { symbol: string; timeframe: string },
  onMessage: WsHandler,
): () => void {
  const s = getSocket();
  const handler = (payload: unknown) => onMessage(payload);

  s.emit("subscribe", room);
  s.on(event, handler);

  return () => {
    s.off(event, handler);
    s.emit("unsubscribe", room);
  };
}
