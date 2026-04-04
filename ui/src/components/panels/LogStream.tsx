export default function LogStream() {
  return (
    <div className="bg-bg-panel p-2 h-full overflow-hidden flex flex-col">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-1">Log Stream</div>
      <div className="overflow-y-auto flex-1 font-mono text-[10px] leading-relaxed text-text-secondary">
        <div className="text-center py-4">Log streaming via WebSocket — connect to /ws/logs</div>
      </div>
    </div>
  );
}
