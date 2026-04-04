import { useEffect, useState, useCallback } from "react";
import { get } from "../api/client";
import type { AnalysisSummary, TradeRow } from "../api/types";
import DataTable from "../components/common/DataTable";
import { toast } from "../components/common/Toast";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Download } from "lucide-react";

const CHART_COLORS = {
  line: "#00e676",
  bar: "#ffab00",
  buy: "#00e676",
  sell: "#ef5350",
  neutral: "#6366f1",
};

const DB_OPTIONS = ["results.db", "backtest.db", "paper_trade.db"];

const TRADE_COLUMNS = [
  { key: "timestamp", label: "Time" },
  { key: "direction", label: "Dir" },
  { key: "pair", label: "Pair" },
  { key: "spread_bps", label: "Spread" },
  { key: "estimated_profit_sol", label: "Est." },
  { key: "simulated_profit_sol", label: "Sim." },
  { key: "dex", label: "DEX" },
  { key: "detector", label: "Detector" },
];

interface TradesResponse {
  trades: TradeRow[];
  total: number;
  page: number;
  per_page: number;
}

function SummaryCard({
  label,
  value,
  color = "text-text-primary",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="bg-bg-panel border border-border rounded p-3 flex flex-col gap-1">
      <span className="text-[10px] text-text-secondary uppercase tracking-wider">{label}</span>
      <span className={`font-mono text-base font-bold ${color}`}>{value}</span>
    </div>
  );
}

export default function Analysis() {
  const [db, setDb] = useState(DB_OPTIONS[0]);
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("timestamp");
  const [direction, setDirection] = useState("");
  const [loading, setLoading] = useState(false);
  const PER_PAGE = 50;

  const fetchSummary = useCallback(async () => {
    try {
      const s = await get<AnalysisSummary & { error?: string }>(`/api/analysis/${db}`);
      if (s.error || !s.total_trades) {
        setSummary(null);
      } else {
        setSummary(s);
      }
    } catch {
      setSummary(null);
    }
  }, [db]);

  const fetchTrades = useCallback(async () => {
    setLoading(true);
    try {
      const res = await get<TradesResponse & { error?: string }>(
        `/api/analysis/${db}/trades?page=${page}&per_page=${PER_PAGE}&sort=${sort}${direction ? `&direction=${direction}` : ""}`
      );
      if (res.error || !res.trades) {
        setTrades([]);
        setTotal(0);
      } else {
        setTrades(res.trades);
        setTotal(res.total);
      }
    } catch {
      setTrades([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [db, page, sort, direction]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  function exportCsv() {
    if (trades.length === 0) {
      toast("No trades to export", "warning");
      return;
    }
    const keys = TRADE_COLUMNS.map((c) => c.key);
    const header = keys.join(",");
    const rows = trades.map((t) =>
      keys.map((k) => JSON.stringify((t as unknown as Record<string, unknown>)[k] ?? "")).join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades_${db}_page${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Build cumulative P&L data for chart
  const pnlData = trades.map((_t, i) => ({
    i: i + 1,
    pnl: trades
      .slice(0, i + 1)
      .reduce((acc, r) => acc + (r.simulated_profit_sol || r.estimated_profit_sol || 0), 0),
  }));

  // Spread distribution
  const spreadBuckets: Record<string, number> = {};
  trades.forEach((t) => {
    const bucket = Math.floor(t.spread_bps / 10) * 10;
    const label = `${bucket}-${bucket + 10}`;
    spreadBuckets[label] = (spreadBuckets[label] ?? 0) + 1;
  });
  const spreadData = Object.entries(spreadBuckets)
    .sort((a, b) => parseInt(a[0]) - parseInt(b[0]))
    .map(([range, count]) => ({ range, count }));

  // Direction breakdown
  const buyCount = trades.filter((t) => t.direction === "BUY_DEX").length;
  const sellCount = trades.filter((t) => t.direction === "SELL_DEX").length;
  const dirData = [
    { name: "BUY_DEX", value: buyCount },
    { name: "SELL_DEX", value: sellCount },
  ].filter((d) => d.value > 0);

  const pageCount = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Analysis
        </h1>
        <div className="flex items-center gap-2">
          <select
            value={db}
            onChange={(e) => {
              setDb(e.target.value);
              setPage(1);
            }}
            className="bg-bg-panel border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
          >
            {DB_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <button
            onClick={exportCsv}
            className="flex items-center gap-1.5 px-3 py-1 text-xs bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors"
          >
            <Download size={11} />
            Export CSV
          </button>
        </div>
      </div>

      {!summary && !loading && (
        <div className="bg-bg-panel border border-border rounded p-8 text-center">
          <p className="text-sm text-text-secondary mb-2">
            No results database found for <span className="font-mono text-accent-amber">{db}</span>
          </p>
          <p className="text-xs text-text-secondary">
            Run a backtest or paper trade first to generate results, then come back here to analyze them.
          </p>
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <SummaryCard label="Total Trades" value={summary.total_trades.toLocaleString()} />
          <SummaryCard
            label="Win Rate"
            value={`${(summary.win_rate * 100).toFixed(1)}%`}
            color={summary.win_rate >= 0.5 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Total P&L"
            value={`${summary.total_profit_sol >= 0 ? "+" : ""}${summary.total_profit_sol.toFixed(4)} SOL`}
            color={summary.total_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Avg Spread"
            value={`${summary.avg_spread_bps.toFixed(1)} bps`}
            color="text-accent-amber"
          />
          <SummaryCard
            label="Avg Profit"
            value={`${summary.avg_profit_sol >= 0 ? "+" : ""}${summary.avg_profit_sol.toFixed(4)} SOL`}
            color={summary.avg_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Best Trade"
            value={`+${summary.best_trade_sol.toFixed(4)} SOL`}
            color="text-accent-green"
          />
          <SummaryCard
            label="Worst Trade"
            value={`${summary.worst_trade_sol.toFixed(4)} SOL`}
            color="text-accent-red"
          />
          <SummaryCard
            label="First Trade"
            value={summary.first_trade ? summary.first_trade.slice(0, 10) : "—"}
          />
        </div>
      )}

      {trades.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-bg-panel border border-border rounded p-3 col-span-3 md:col-span-1">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
              P&amp;L Over Time
            </div>
            <ResponsiveContainer width="100%" height={140}>
              <LineChart data={pnlData} margin={{ top: 2, right: 8, left: -20, bottom: 2 }}>
                <XAxis dataKey="i" tick={{ fontSize: 9, fill: "#7f8ea3" }} />
                <YAxis tick={{ fontSize: 9, fill: "#7f8ea3" }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#16213e",
                    border: "1px solid #2a2a4a",
                    fontSize: 10,
                    color: "#e0e0e0",
                  }}
                  formatter={(v: unknown) => [typeof v === "number" ? v.toFixed(4) : String(v ?? ""), "P&L"]}
                />
                <Line
                  type="monotone"
                  dataKey="pnl"
                  stroke={CHART_COLORS.line}
                  dot={false}
                  strokeWidth={1.5}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-bg-panel border border-border rounded p-3 col-span-3 md:col-span-1">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
              Spread Distribution
            </div>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={spreadData} margin={{ top: 2, right: 8, left: -20, bottom: 2 }}>
                <XAxis dataKey="range" tick={{ fontSize: 9, fill: "#7f8ea3" }} />
                <YAxis tick={{ fontSize: 9, fill: "#7f8ea3" }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#16213e",
                    border: "1px solid #2a2a4a",
                    fontSize: 10,
                    color: "#e0e0e0",
                  }}
                />
                <Bar dataKey="count" fill={CHART_COLORS.bar} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-bg-panel border border-border rounded p-3 col-span-3 md:col-span-1">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
              Direction Breakdown
            </div>
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie
                  data={dirData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={55}
                  label={({ name, percent }: { name?: string; percent?: number }) =>
                    `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                  }
                  labelLine={false}
                  fontSize={9}
                >
                  <Cell fill={CHART_COLORS.buy} />
                  <Cell fill={CHART_COLORS.sell} />
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#16213e",
                    border: "1px solid #2a2a4a",
                    fontSize: 10,
                    color: "#e0e0e0",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="bg-bg-panel border border-border rounded overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-border">
          <span className="text-[10px] text-text-secondary uppercase tracking-wider">
            Trades {total > 0 ? `(${total.toLocaleString()})` : ""}
          </span>
          <div className="flex items-center gap-2">
            <select
              value={sort}
              onChange={(e) => { setSort(e.target.value); setPage(1); }}
              className="bg-bg-main border border-border rounded px-2 py-0.5 text-[10px] focus:outline-none focus:border-accent-indigo"
            >
              <option value="timestamp">Sort: Time</option>
              <option value="spread_bps">Sort: Spread</option>
              <option value="estimated_profit_sol">Sort: Profit</option>
            </select>
            <select
              value={direction}
              onChange={(e) => { setDirection(e.target.value); setPage(1); }}
              className="bg-bg-main border border-border rounded px-2 py-0.5 text-[10px] focus:outline-none focus:border-accent-indigo"
            >
              <option value="">All directions</option>
              <option value="BUY_DEX">BUY_DEX</option>
              <option value="SELL_DEX">SELL_DEX</option>
            </select>
          </div>
        </div>
        {loading ? (
          <div className="py-8 text-center text-xs text-text-secondary">Loading…</div>
        ) : (
          <DataTable
            columns={TRADE_COLUMNS}
            data={trades as unknown as Record<string, unknown>[]}
            sortable={false}
            pagination={
              pageCount > 1
                ? { page, totalPages: pageCount, onPageChange: setPage }
                : undefined
            }
          />
        )}
      </div>
    </div>
  );
}
