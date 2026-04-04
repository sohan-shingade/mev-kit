export function createWebSocket(
  path: string,
  onMessage: (data: unknown) => void,
  onStatusChange?: (connected: boolean) => void
): { close: () => void } {
  let ws: WebSocket | null = null;
  let backoff = 1000;
  const maxBackoff = 30000;
  let stopped = false;

  function connect() {
    if (stopped) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${window.location.host}${path}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
      backoff = 1000;
      onStatusChange?.(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch { /* ignore parse errors */ }
    };

    ws.onclose = () => {
      onStatusChange?.(false);
      if (!stopped) {
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, maxBackoff);
      }
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  connect();

  return {
    close: () => {
      stopped = true;
      ws?.close();
    },
  };
}
