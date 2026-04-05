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
    <div className="h-[20px] bg-[#07070c] border-t border-[#1c1a28] flex items-center px-1.5 gap-0 text-[9px] select-none shrink-0 overflow-hidden">
      {/* Pipeline state */}
      <div className="flex items-center gap-1.5 px-1.5 border-r border-[#1c1a28]">
        <div className={`w-1.5 h-1.5 rounded-full ${
          running ? "bg-[#14f195]" : (status?.state as string) === "error" ? "bg-[#f43f5e]" : "bg-[#1c1a28]"
        }`} />
        <span className={running ? "text-[#14f195]" : "text-[#2a2838]"}>
          {running ? `${status?.mode?.toUpperCase()}` : "IDLE"}
        </span>
      </div>

      {/* Live metrics */}
      {running && hasMetrics && (
        <>
          <div className="px-1.5 border-r border-[#1c1a28] text-[#56516a]">
            pnl{" "}
            <span className={m!.total_profit_sol >= 0 ? "text-[#14f195]" : "text-[#f43f5e]"}>
              {m!.total_profit_sol >= 0 ? "+" : ""}{m!.total_profit_sol.toFixed(4)}
            </span>
          </div>
          <div className="px-1.5 border-r border-[#1c1a28] text-[#56516a]">
            opp <span className="text-[#d0d4dc]">{m!.opportunities_detected}</span>
          </div>
          <div className="px-1.5 border-r border-[#1c1a28] text-[#56516a]">
            exec <span className="text-[#d0d4dc]">{m!.opportunities_executed}</span>
          </div>
          <div className="px-1.5 border-r border-[#1c1a28] text-[#56516a]">
            q <span className="text-[#d0d4dc]">{m!.queue_size}</span>
          </div>
        </>
      )}

      <div className="flex-1" />

      {/* Solana branding hint */}
      <div className="px-1.5 border-l border-[#1c1a28] text-[#1c1a28]">
        solana
      </div>
      <div className="px-1.5 border-l border-[#1c1a28] text-[#2a2838] tabular-nums">
        {time.toLocaleTimeString("en-US", { hour12: false })}
      </div>
    </div>
  );
}
