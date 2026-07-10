/**
 * WebSocket client with auto-reconnect.
 * Phase 1 will stream candles/ticks; Phase 3 adds positions and bot events.
 *
 * Next.js rewrites only proxy HTTP, not WebSockets, so this connects to the
 * backend directly. Configure NEXT_PUBLIC_WS_URL when the backend is not on
 * the default dev address (paths are backend-native, no /api prefix).
 */

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://127.0.0.1:8000";

export type WsHandler = (message: unknown) => void;

export function connectWs(path: string, onMessage: WsHandler): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retryMs = 1000;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${WS_BASE}${path}`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onopen = () => {
      retryMs = 1000;
    };
    ws.onclose = () => {
      if (!closed) {
        setTimeout(open, retryMs);
        retryMs = Math.min(retryMs * 2, 15000);
      }
    };
  };

  open();
  return () => {
    closed = true;
    ws?.close();
  };
}
