import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import type { Opportunity } from "../../api/types";

interface Props {
  opportunities: Opportunity[];
}

export default function PnlChart({ opportunities }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#16213e" },
        textColor: "#7f8ea3",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "#2a2a4a" },
        horzLines: { color: "#2a2a4a" },
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      rightPriceScale: { borderColor: "#2a2a4a" },
      timeScale: { borderColor: "#2a2a4a" },
    });
    const series = chart.addSeries(LineSeries, { color: "#00e676", lineWidth: 2 });
    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || opportunities.length === 0) return;
    let cumulative = 0;
    const data: LineData<Time>[] = opportunities
      .slice()
      .reverse()
      .map((opp, i) => {
        cumulative += opp.simulated_profit_sol ?? opp.estimated_profit_sol;
        return { time: (i + 1) as unknown as Time, value: cumulative };
      });
    seriesRef.current.setData(data);
  }, [opportunities]);

  return (
    <div className="bg-bg-panel p-2 h-full">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-1">
        Cumulative P&L
      </div>
      <div
        ref={containerRef}
        className="w-full"
        style={{ height: "calc(100% - 20px)" }}
      />
    </div>
  );
}
