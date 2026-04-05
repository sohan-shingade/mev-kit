import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { PipelineStatus } from "../api/types";

export default function StatusBar() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        setStatus(await get<PipelineStatus>("/api/pipeline/status"));
      } catch {/* */}
    }, 2000);
    const clock = setInterval(() => setTime(new Date()), 1000);
    return () => { clearInterval(poll); clearInterval(clock); };
  }, []);

  const m = status?.metrics;
  const running = status?.state === "running";
  const hasMetrics = m && "total_profit_sol" in m;

  return (
    <div className="h-[22px] bg-[#070910] border-t border-[#141720] flex items-center px-2 gap-0 text-[10px] font-mono select-none shrink-0 overflow-hidden">
      {/* Pipeline state */}
      <div className="flex items-center gap-1.5 px-2 border-r border-[#141720]">
        <div className={`w-1.5 h-1.5 rounded-full ${
          running ? "bg-accent-green animate-pulse" : (status?.state as string) === "error" ? "bg-accent-red" : "bg-[#2e3340]"
        }`} />
        <span className={running ? "text-accent-green" : "text-[#3a4050]"}>
          {running ? `${status?.mode?.toUpperCase()} ACTIVE` : "IDLE"}
        </span>
      </div>

      {/* Live metrics ticker */}
      {running && hasMetrics && (
        <>
          <div className="px-2 border-r border-[#141720] text-text-secondary">
            P&L <span className={m!.total_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}>
              {m!.total_profit_sol >= 0 ? "+" : ""}{m!.total_profit_sol.toFixed(4)}
            </span>
          </div>
          <div className="px-2 border-r border-[#141720] text-text-secondary">
            OPP <span className="text-text-primary">{m!.opportunities_detected}</span>
          </div>
          <div className="px-2 border-r border-[#141720] text-text-secondary">
            EXEC <span className="text-text-primary">{m!.opportunities_executed}</span>
          </div>
          <div className="px-2 border-r border-[#141720] text-text-secondary">
            Q <span className="text-text-primary">{m!.queue_size}</span>
          </div>
        </>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Version + clock */}
      <div className="px-2 border-l border-[#141720] text-[#2e3340]">
        mev-kit v0.1.0
      </div>
      <div className="px-2 border-l border-[#141720] text-[#3a4050] tabular-nums">
        {time.toLocaleTimeString("en-US", { hour12: false })}
      </div>
    </div>
  );
}
