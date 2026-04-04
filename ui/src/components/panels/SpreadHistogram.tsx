import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Opportunity } from "../../api/types";

interface Props {
  opportunities: Opportunity[];
}

const BUCKETS = [
  { label: "0-20", min: 0, max: 20 },
  { label: "20-50", min: 20, max: 50 },
  { label: "50-100", min: 50, max: 100 },
  { label: "100-200", min: 100, max: 200 },
  { label: "200+", min: 200, max: Infinity },
];

const COLORS = ["#0d47a1", "#1565c0", "#1976d2", "#1e88e5", "#42a5f5"];

export default function SpreadHistogram({ opportunities }: Props) {
  const data = useMemo(() => {
    return BUCKETS.map((b) => ({
      name: b.label,
      count: opportunities.filter(
        (o) => o.spread_bps >= b.min && o.spread_bps < b.max
      ).length,
    }));
  }, [opportunities]);

  return (
    <div className="bg-bg-panel p-2 h-full">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-1">
        Spread Distribution
      </div>
      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={data}>
          <XAxis
            dataKey="name"
            tick={{ fill: "#7f8ea3", fontSize: 9 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#7f8ea3", fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            width={30}
          />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
