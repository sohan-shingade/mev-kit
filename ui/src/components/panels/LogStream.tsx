import { useWebSocket } from "../../hooks/useWebSocket";

interface LogEntry {
  type: string;
  level: string;
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export default function LogStream() {
  const { data } = useWebSocket<LogEntry>("/api/pipeline/ws");
  // For now, show a placeholder since we don't have a separate log WS yet
  return (
    <div className="bg-bg-panel p-2 h-full overflow-hidden flex flex-col">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-1">
        Log Stream
      </div>
      <div className="overflow-y-auto flex-1 font-mono text-[10px] leading-relaxed text-text-secondary">
        {data ? (
          <div>
            <span className="text-text-secondary/60">
              {new Date().toLocaleTimeString("en-US", { hour12: false })}
            </span>{" "}
            {data.event ?? JSON.stringify(data)}
          </div>
        ) : (
          <div className="text-center py-4">Waiting for logs...</div>
        )}
      </div>
    </div>
  );
}
