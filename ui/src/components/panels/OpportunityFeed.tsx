import type { Opportunity } from "../../api/types";

interface Props {
  opportunities: Opportunity[];
}

export default function OpportunityFeed({ opportunities }: Props) {
  return (
    <div className="bg-bg-panel p-2 h-full overflow-hidden flex flex-col">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-1">
        Live Opportunity Feed
      </div>
      <div className="flex text-[9px] text-text-secondary uppercase tracking-wider border-b border-border pb-1 mb-1 gap-2">
        <span className="w-16">Time</span>
        <span className="w-14">Dir</span>
        <span className="w-16">Spread</span>
        <span className="w-18">Est P&L</span>
        <span className="w-18">Sim P&L</span>
        <span className="w-12">Lat</span>
        <span className="w-6">St</span>
      </div>
      <div className="overflow-y-auto flex-1 font-mono text-[11px] leading-relaxed">
        {opportunities.map((opp) => {
          const time = new Date(opp.timestamp).toLocaleTimeString("en-US", {
            hour12: false,
            fractionalSecondDigits: 1,
          } as Intl.DateTimeFormatOptions);
          const dirColor =
            opp.direction === "BUY_DEX"
              ? "text-accent-green"
              : "text-accent-red";
          const plColor = opp.success
            ? "text-accent-green"
            : "text-accent-red";
          return (
            <div key={opp.id} className="flex gap-2 py-px">
              <span className="w-16 text-text-secondary">{time}</span>
              <span className={`w-14 ${dirColor}`}>
                {opp.direction === "BUY_DEX" ? "BUY" : "SELL"}
              </span>
              <span className="w-16">{(opp.spread_bps ?? 0).toFixed(1)} bps</span>
              <span className="w-18">
                {(opp.estimated_profit_sol ?? 0) >= 0 ? "+" : ""}
                {(opp.estimated_profit_sol ?? 0).toFixed(4)}
              </span>
              <span className={`w-18 ${plColor}`}>
                {(opp.simulated_profit_sol ?? 0) >= 0 ? "+" : ""}
                {(opp.simulated_profit_sol ?? 0).toFixed(4)}
              </span>
              <span className="w-12 text-text-secondary">
                {(opp.sim_latency_ms ?? 0).toFixed(0)}ms
              </span>
              <span className={`w-6 ${plColor}`}>
                {opp.success ? "✓" : "✗"}
              </span>
            </div>
          );
        })}
        {opportunities.length === 0 && (
          <div className="text-text-secondary text-center py-4">
            No opportunities yet
          </div>
        )}
      </div>
    </div>
  );
}
