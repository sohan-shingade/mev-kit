import type { PipelineMetrics } from "../../api/types";

interface Props {
  metrics: PipelineMetrics | null;
  state: string;
  mode: string | null;
}

export default function MetricsStrip({ metrics, state, mode }: Props) {
  const m = metrics;
  const items = [
    {
      label: "P&L",
      value: m
        ? `${m.total_profit_sol >= 0 ? "+" : ""}${m.total_profit_sol.toFixed(4)}`
        : "—",
      color:
        m && m.total_profit_sol >= 0 ? "text-accent-green" : "text-accent-red",
    },
    {
      label: "WIN%",
      value: m
        ? `${(m.opportunities_executed > 0 ? ((m.opportunities_profitable / m.opportunities_executed) * 100) : 0).toFixed(1)}`
        : "—",
      color: "text-text-primary",
    },
    {
      label: "OPP/m",
      value:
        m && m.elapsed_seconds > 0
          ? `${(m.opportunities_detected / (m.elapsed_seconds / 60)).toFixed(1)}`
          : "—",
      color: "text-accent-amber",
    },
    {
      label: "UPDATES",
      value: m ? m.updates_processed.toLocaleString() : "—",
      color: "text-text-primary",
    },
    {
      label: "QUEUE",
      value: m ? String(m.queue_size) : "—",
      color: "text-text-primary",
    },
    {
      label: "DETECT%",
      value: m ? `${(m.detection_rate * 100).toFixed(1)}` : "—",
      color: "text-text-primary",
    },
  ];

  return (
    <div className="flex gap-0.5">
      {state !== "idle" && (
        <div className="bg-bg-panel px-3 py-1.5 flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              state === "running"
                ? "bg-accent-green animate-pulse"
                : "bg-text-secondary"
            }`}
          />
          <span className="text-xs font-mono uppercase">{mode ?? state}</span>
        </div>
      )}
      {items.map(({ label, value, color }) => (
        <div
          key={label}
          className="bg-bg-panel px-3 py-1.5 flex-1 flex justify-between items-center min-w-0"
        >
          <span className="text-[10px] text-text-secondary uppercase tracking-wider">
            {label}
          </span>
          <span className={`font-mono text-sm font-bold ${color}`}>{value}</span>
        </div>
      ))}
    </div>
  );
}
