/**
 * WebSocket client with auto-reconnect.
 * Phase 1 will stream candles/ticks; Phase 3 adds positions and bot events.
 */

export type WsHandler = (message: unknown) => void;

export function connectWs(path: string, onMessage: WsHandler): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retryMs = 1000;

  const open = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api${path}`);
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
