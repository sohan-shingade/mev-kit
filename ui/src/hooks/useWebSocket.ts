import { useEffect, useRef, useState } from "react";
import { createWebSocket } from "../api/ws";

export function useWebSocket<T>(path: string): { data: T | null; connected: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<{ close: () => void } | null>(null);

  useEffect(() => {
    wsRef.current = createWebSocket(
      path,
      (msg) => setData(msg as T),
      (status) => setConnected(status)
    );
    return () => wsRef.current?.close();
  }, [path]);

  return { data, connected };
}
