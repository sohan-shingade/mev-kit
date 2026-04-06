import { useEffect, useRef, useState } from "react";
import { get, post } from "../api/client";
import type { BacktestStatus, DataFile, SweepResultRow, SweepStatus, TradeRow, WalkForwardResult } from "../api/types";
import DataTable from "../components/common/DataTable";
import { toast } from "../components/common/Toast";
import { Play, Square, RotateCcw, Download, ChevronDown, ChevronUp, Trash2, Search, FlaskConical, GitCompare, Plus, X } from "lucide-react";
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface StrategyOption {
  name: string;
  path: string;
  type: "user" | "example" | "builtin";
}

const BUILTIN_STRATEGIES: StrategyOption[] = [
  { name: "CEX-DEX Arb", path: "cex_dex_arb", type: "builtin" },
];

interface BacktestConfig {
  data_file: string;
  cex_data_file: string;
  strategy: string;
  min_spread_bps: number;
  fee_bps: number;
  position_size_sol: number;
  simulate_before_execute: boolean;
  use_sources: string[];
  venue: string;
  simulate_fills: boolean;
  extra_data_files: string[];
}

interface FileSource {
  type: string;
  venue: string;
  status: string;
}

interface FileSources {
  sources: FileSource[];
  merged: boolean;
  columns: string[];
  error?: string;
}

interface StrategyInfo {
  name: string;
  required_sources: string[];
  needs_cex: boolean;
  needs_dex: boolean;
  needs_dual_source: boolean;
  hyperparameters: Record<string, { min: number; max: number; step: number }>;
  warmup_updates: number;
  error?: string;
}

interface RunHistoryEntry {
  id: string;
  timestamp: string;
  strategy: string;
  data_file: string;
  min_spread_bps: number;
  fee_bps: number;
  position_size_sol: number;
  venue: string;
  total_trades: number;
  total_profit_sol: number;
  results: BacktestStatus["results"];
}

interface SweepParamConfig {
  min: number;
  max: number;
  step: number;
}

const HISTORY_KEY = "backtest_run_history";
const MAX_HISTORY = 10;

function loadHistory(): RunHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as RunHistoryEntry[];
  } catch {
    return [];
  }
}

function saveHistory(entries: RunHistoryEntry[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)));
  } catch {
    // ignore storage errors
  }
}

const TRADE_COLUMNS = [
  { key: "detected_at", label: "Time" },
  { key: "direction", label: "Dir" },
  { key: "pair", label: "Pair" },
  { key: "spread_bps", label: "Spread bps" },
  { key: "estimated_profit_sol", label: "Est. Profit" },
  { key: "simulated_profit_sol", label: "Sim. Profit" },
  { key: "dex", label: "DEX" },
];

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
      <span className={`font-mono text-lg font-bold ${color}`}>{value}</span>
    </div>
  );
}

function exportTradesToCsv(trades: TradeRow[], filename: string) {
  if (trades.length === 0) {
    toast("No trades to export", "warning");
    return;
  }
  const keys = TRADE_COLUMNS.map((c) => c.key);
  const header = keys.join(",");
  const rows = trades.map((t) =>
    keys
      .map((k) => JSON.stringify((t as unknown as Record<string, unknown>)[k] ?? ""))
      .join(",")
  );
  const csv = [header, ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Backtest() {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [strategies, setStrategies] = useState<StrategyOption[]>(BUILTIN_STRATEGIES);
  const [config, setConfig] = useState<BacktestConfig>({
    data_file: "",
    cex_data_file: "",
    strategy: "cex_dex_arb",
    min_spread_bps: 5,
    fee_bps: 10,
    position_size_sol: 0.1,
    simulate_before_execute: true,
    use_sources: [],  // empty = use all available
    venue: "aggregated",
    simulate_fills: true,
    extra_data_files: [],
  });
  const [status, setStatus] = useState<BacktestStatus>({ state: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [page, setPage] = useState(1);
  const PER_PAGE = 50;

  const [strategyInfo, setStrategyInfo] = useState<StrategyInfo | null>(null);
  const [fileSources, setFileSources] = useState<FileSources | null>(null);

  // Fetch file source info when data file changes
  useEffect(() => {
    if (!config.data_file) { setFileSources(null); return; }
    get<FileSources>(`/api/data/files/${config.data_file}/sources`)
      .then((info) => { if (!info.error) setFileSources(info); })
      .catch(() => setFileSources(null));
  }, [config.data_file]);

  // Auto-set execution venue based on selected data sources
  useEffect(() => {
    if (!fileSources) return;
    const activeSources = config.use_sources.length > 0
      ? fileSources.sources.filter((s) => config.use_sources.includes(s.type))
      : fileSources.sources;

    const hasCex = activeSources.some((s) => s.type === "cex");
    const hasDex = activeSources.some((s) => s.type === "dex");

    if (hasCex && !hasDex) {
      // Only CEX data selected — match venue to the CEX source
      const cexSource = activeSources.find((s) => s.type === "cex");
      const venueName = cexSource?.venue?.toLowerCase() ?? "";
      if (venueName.includes("binance")) {
        setConfig((c) => c.venue !== "binance" ? { ...c, venue: "binance" } : c);
      } else if (venueName.includes("coinbase")) {
        setConfig((c) => c.venue !== "coinbase" ? { ...c, venue: "coinbase" } : c);
      }
    } else if (hasDex && !hasCex) {
      // Only DEX data — use a DEX venue
      const dexVenues = ["jupiter", "raydium", "orca", "aggregated"];
      if (!dexVenues.includes(config.venue)) {
        setConfig((c) => ({ ...c, venue: "aggregated" }));
      }
    }
  }, [fileSources, config.use_sources]);

  // Recent runs history
  const [history, setHistory] = useState<RunHistoryEntry[]>(loadHistory);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);

  // ── Sweep state (Phase 4) ──
  const [sweepOpen, setSweepOpen] = useState(false);
  const [sweepParams, setSweepParams] = useState<Record<string, SweepParamConfig>>({
    min_spread_bps: { min: 3, max: 15, step: 3 },
    fee_bps: { min: 5, max: 20, step: 5 },
    position_size_sol: { min: 0.05, max: 0.5, step: 0.05 },
  });
  const [sweepStatus, setSweepStatus] = useState<SweepStatus>({ state: "idle", progress: 0, total: 0 });
  const sweepPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [walkForward, setWalkForward] = useState(false);
  const [trainPct, setTrainPct] = useState(0.7);

  // ── Comparison state (Phase 4) ──
  const [compareIds, setCompareIds] = useState<[string | null, string | null]>([null, null]);
  const [compareOpen, setCompareOpen] = useState(false);

  // Fetch strategy info when strategy changes
  useEffect(() => {
    if (!config.strategy) return;
    get<StrategyInfo>(`/api/strategies/info/${config.strategy}`)
      .then((info) => {
        if (!info.error) setStrategyInfo(info);
      })
      .catch(() => setStrategyInfo(null));
  }, [config.strategy]);

  useEffect(() => {
    get<DataFile[]>("/api/data/files")
      .then((f) => {
        setFiles(f);
        if (f.length > 0) setConfig((c) => ({ ...c, data_file: f[0].name }));
      })
      .catch(() => {});
    // Load available strategies
    get<{ name: string; path: string; type: string }[]>("/api/strategies/files")
      .then((s) => {
        const opts: StrategyOption[] = [...BUILTIN_STRATEGIES];
        for (const f of s) {
          const key = f.path.replace(".py", "").replace("examples/", "");
          if (key === "cex_dex_arb") continue; // already in builtins
          opts.push({
            name: f.name.replace(".py", "").replace(/_/g, " "),
            path: key,
            type: f.type as "user" | "example",
          });
        }
        setStrategies(opts);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (status.state === "running") {
      pollRef.current = setInterval(async () => {
        try {
          const s = await get<BacktestStatus>("/api/backtest/status");
          setStatus(s);
          if (s.state !== "running") {
            clearInterval(pollRef.current!);
            // Save to history if completed with results
            if (s.state === "completed" && s.results) {
              const entry: RunHistoryEntry = {
                id: s.results.run_id ?? `${Date.now()}`,
                timestamp: s.results.run_timestamp ?? new Date().toISOString(),
                strategy: config.strategy,
                data_file: config.data_file,
                min_spread_bps: config.min_spread_bps,
                fee_bps: config.fee_bps,
                position_size_sol: config.position_size_sol,
                venue: config.venue,
                total_trades: s.results.total_trades,
                total_profit_sol: s.results.total_profit_sol,
                results: s.results,
              };
              setHistory((prev) => {
                const updated = [entry, ...prev].slice(0, MAX_HISTORY);
                saveHistory(updated);
                return updated;
              });
            }
          }
        } catch {
          clearInterval(pollRef.current!);
        }
      }, 1000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status.state, config]);

  async function handleStart() {
    if (!config.data_file) {
      toast("Select a data file first", "warning");
      return;
    }
    try {
      const payload: Record<string, unknown> = { ...config };
      // Only pass extra_data_files if non-empty
      if (config.extra_data_files.length === 0) {
        delete payload.extra_data_files;
      }
      await post("/api/backtest/start", payload);
      setStatus({ state: "running" });
      setPage(1);
      setSelectedHistoryId(null);
    } catch {
      toast("Failed to start backtest", "error");
    }
  }

  async function handleCancel() {
    try { await post("/api/backtest/stop", {}); } catch {}
    setStatus({ state: "idle" });
    if (pollRef.current) clearInterval(pollRef.current);
  }

  function handleReset() {
    setStatus({ state: "idle" });
    setPage(1);
    setSelectedHistoryId(null);
  }

  function handleClearHistory() {
    setHistory([]);
    saveHistory([]);
    setSelectedHistoryId(null);
  }

  function handleSelectHistoryRun(entry: RunHistoryEntry) {
    setSelectedHistoryId(entry.id);
    setStatus({ state: "completed", results: entry.results });
    setPage(1);
  }

  // ── Sweep helpers (Phase 4) ──
  function generateSweepValues(p: SweepParamConfig): number[] {
    const values: number[] = [];
    for (let v = p.min; v <= p.max + 1e-9; v += p.step) {
      values.push(Math.round(v * 1000) / 1000);
    }
    return values;
  }

  function sweepTotalCombinations(): number {
    return Object.values(sweepParams).reduce(
      (acc, p) => acc * generateSweepValues(p).length,
      1,
    );
  }

  async function handleStartSweep() {
    if (!config.data_file) {
      toast("Select a data file first", "warning");
      return;
    }
    const sweep: Record<string, number[]> = {};
    for (const [key, p] of Object.entries(sweepParams)) {
      sweep[key] = generateSweepValues(p);
    }

    const endpoint = walkForward ? "/api/backtest/walk-forward" : "/api/backtest/sweep";
    const body: Record<string, unknown> = {
      data_file: config.data_file,
      strategy: config.strategy,
      sweep,
      config: {
        venue: config.venue,
        simulate_fills: config.simulate_fills,
      },
    };
    if (walkForward) {
      body.train_pct = trainPct;
    }

    try {
      await post(endpoint, body);
      setSweepStatus({ state: "running", progress: 0, total: sweepTotalCombinations() });
      // Start polling
      if (sweepPollRef.current) clearInterval(sweepPollRef.current);
      sweepPollRef.current = setInterval(async () => {
        try {
          const s = await get<SweepStatus>("/api/backtest/sweep/status");
          setSweepStatus(s);
          if (s.state !== "running") {
            clearInterval(sweepPollRef.current!);
            sweepPollRef.current = null;
          }
        } catch {
          clearInterval(sweepPollRef.current!);
          sweepPollRef.current = null;
        }
      }, 1500);
    } catch {
      toast("Failed to start sweep", "error");
    }
  }

  function handleUseBestParams(params: Record<string, number>) {
    setConfig((c) => ({
      ...c,
      min_spread_bps: params.min_spread_bps ?? c.min_spread_bps,
      fee_bps: params.fee_bps ?? c.fee_bps,
      position_size_sol: params.position_size_sol ?? c.position_size_sol,
    }));
    toast("Best params applied to config", "success");
  }

  // ── Comparison helpers (Phase 4) ──
  function toggleCompare(id: string) {
    setCompareIds(([a, b]) => {
      if (a === id) return [null, b];
      if (b === id) return [a, null];
      if (!a) return [id, b];
      if (!b) return [a, id];
      return [id, b]; // replace first
    });
  }

  const compareA = compareIds[0] ? history.find((h) => h.id === compareIds[0]) : null;
  const compareB = compareIds[1] ? history.find((h) => h.id === compareIds[1]) : null;

  // Determine active results (from current run or selected history entry)
  const activeResults =
    status.state === "completed" && status.results ? status.results : null;

  const trades: TradeRow[] = (activeResults?.trades ?? []).map((t: TradeRow): TradeRow => ({
    ...t,
    detected_at: t.detected_at ?? t.timestamp,
  }));
  const pageCount = Math.max(1, Math.ceil(trades.length / PER_PAGE));
  const pagedTrades = trades.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  if (status.state === "running") {
    const prog = status.progress;
    return (
      <div className="p-4 flex flex-col gap-4 max-w-2xl">
        <div className="flex items-center justify-between">
          <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
            Backtest Running
          </h1>
          <button
            onClick={handleCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent-red/10 border border-accent-red/40 text-accent-red rounded hover:bg-accent-red/20 transition-colors"
          >
            <Square size={12} />
            Cancel
          </button>
        </div>
        <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-accent-green animate-pulse" />
            <span className="text-sm font-mono text-accent-green">Processing...</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-0.5">
              <span className="text-[10px] text-text-secondary uppercase tracking-wider">
                Updates Processed
              </span>
              <span className="font-mono text-xl font-bold text-text-primary">
                {(prog?.updates_processed ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-[10px] text-text-secondary uppercase tracking-wider">
                Opportunities Detected
              </span>
              <span className="font-mono text-xl font-bold text-accent-amber">
                {(prog?.opportunities_detected ?? 0).toLocaleString()}
              </span>
            </div>
          </div>
          <div className="w-full h-1.5 bg-bg-main rounded-full overflow-hidden">
            <div
              className="h-full bg-accent-indigo rounded-full transition-all"
              style={{
                width: prog
                  ? `${Math.min(100, (prog.updates_processed / 10000) * 100)}%`
                  : "10%",
                animation: "pulse 1s ease-in-out infinite",
              }}
            />
          </div>
        </div>
      </div>
    );
  }

  if (status.state === "completed" && activeResults) {
    const r = activeResults;
    return (
      <div className="p-4 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
            {selectedHistoryId ? "Backtest (History)" : "Backtest Complete"}
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() =>
                exportTradesToCsv(
                  trades,
                  `backtest_${r.total_trades}trades_${new Date().toISOString().slice(0, 10)}.csv`
                )
              }
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors"
            >
              <Download size={12} />
              Export CSV
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors"
            >
              <RotateCcw size={12} />
              Tweak &amp; Re-run
            </button>
            <button
              onClick={async () => {
                try {
                  await post("/api/pipeline/start-from-backtest", {
                    run_config: r.run_config,
                  });
                  toast("Paper trading started with backtest params", "success");
                  window.location.href = "/";
                } catch {
                  toast("Failed to start paper trading", "error");
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent-green/10 border border-accent-green/30 text-accent-green rounded hover:bg-accent-green/20 transition-colors"
            >
              Go Paper &rarr;
            </button>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <SummaryCard label="Total Trades" value={r.total_trades.toLocaleString()} />
          <SummaryCard
            label="Win Rate"
            value={`${(r.win_rate * 100).toFixed(1)}%`}
            color={r.win_rate >= 0.5 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Total P&L"
            value={`${r.total_profit_sol >= 0 ? "+" : ""}${r.total_profit_sol.toFixed(4)} SOL`}
            color={r.total_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Avg Spread"
            value={`${r.avg_spread_bps.toFixed(1)} bps`}
            color="text-accent-amber"
          />
          <SummaryCard
            label="Avg Profit"
            value={`${r.avg_profit_sol >= 0 ? "+" : ""}${r.avg_profit_sol.toFixed(4)} SOL`}
            color={r.avg_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}
          />
          <SummaryCard
            label="Best Trade"
            value={`+${r.best_trade_sol.toFixed(4)} SOL`}
            color="text-accent-green"
          />
          <SummaryCard
            label="Worst Trade"
            value={`${r.worst_trade_sol.toFixed(4)} SOL`}
            color="text-accent-red"
          />
        </div>

        {r.fill_stats && (
          <div className="bg-bg-panel/30 border border-border/40 rounded p-3">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
              Fill Simulation — {r.fill_stats.venue_label}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
              <div>
                <span className="text-text-secondary">Opportunities</span>
                <span className="block font-mono text-text-primary">{r.fill_stats.total_simulated.toLocaleString()}</span>
              </div>
              <div>
                <span className="text-text-secondary">Landed</span>
                <span className="block font-mono text-accent-green">{r.fill_stats.total_landed.toLocaleString()}</span>
              </div>
              <div>
                <span className="text-text-secondary">Landing Rate</span>
                <span className="block font-mono text-accent-amber">{(r.fill_stats.landing_rate_actual * 100).toFixed(1)}%</span>
              </div>
              <div>
                <span className="text-text-secondary">Venue Fee</span>
                <span className="block font-mono text-text-primary">{r.fill_stats.fee_bps} bps</span>
              </div>
            </div>
          </div>
        )}

        {r.cost_breakdown && (
          <div className="bg-bg-panel/30 border border-border/40 rounded p-3">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
              Average Cost Per Trade
            </div>
            <div className="grid grid-cols-5 gap-2 text-xs">
              <div>
                <span className="text-text-secondary block">Venue Fee</span>
                <span className="font-mono text-text-primary">{r.cost_breakdown.avg_venue_fee_bps} bps</span>
              </div>
              <div>
                <span className="text-text-secondary block">Slippage</span>
                <span className="font-mono text-accent-amber">{r.cost_breakdown.avg_slippage_bps} bps</span>
              </div>
              <div>
                <span className="text-text-secondary block">Staleness</span>
                <span className="font-mono text-text-primary">{r.cost_breakdown.avg_staleness_bps} bps</span>
              </div>
              <div>
                <span className="text-text-secondary block">Tip</span>
                <span className="font-mono text-text-primary">{r.cost_breakdown.avg_tip_bps}%</span>
              </div>
              <div>
                <span className="text-text-secondary block">Land Rate</span>
                <span className="font-mono text-accent-green">{(r.cost_breakdown.landing_rate * 100).toFixed(1)}%</span>
              </div>
            </div>
          </div>
        )}

        {/* Risk Metrics Cards (Phase 3) */}
        {r.risk_metrics && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <SummaryCard
              label="Sharpe Ratio"
              value={r.risk_metrics.sharpe_ratio.toFixed(2)}
              color={r.risk_metrics.sharpe_ratio > 1 ? "text-accent-green" : r.risk_metrics.sharpe_ratio > 0 ? "text-accent-amber" : "text-accent-red"}
            />
            <SummaryCard
              label="Max Drawdown"
              value={`${r.risk_metrics.max_drawdown_sol.toFixed(4)} SOL`}
              color="text-accent-red"
            />
            <SummaryCard
              label="Profit Factor"
              value={r.risk_metrics.profit_factor > 100 ? "\u221E" : r.risk_metrics.profit_factor.toFixed(2)}
              color={r.risk_metrics.profit_factor > 1.5 ? "text-accent-green" : "text-accent-amber"}
            />
            <SummaryCard
              label="Sortino Ratio"
              value={r.risk_metrics.sortino_ratio > 100 ? "\u221E" : r.risk_metrics.sortino_ratio.toFixed(2)}
              color={r.risk_metrics.sortino_ratio > 1.5 ? "text-accent-green" : "text-accent-amber"}
            />
            <SummaryCard label="Avg Win" value={`+${r.risk_metrics.avg_win_sol.toFixed(6)} SOL`} color="text-accent-green" />
            <SummaryCard label="Avg Loss" value={`${r.risk_metrics.avg_loss_sol.toFixed(6)} SOL`} color="text-accent-red" />
            <SummaryCard label="Win Streak" value={String(r.risk_metrics.max_win_streak)} />
            <SummaryCard label="Loss Streak" value={String(r.risk_metrics.max_loss_streak)} color="text-accent-red" />
          </div>
        )}

        {/* Equity Curve & Drawdown Chart (Phase 3) */}
        {r.equity_curve && r.equity_curve.length > 0 && (
          <div className="bg-bg-panel/30 border border-border/40 rounded p-3">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">Equity Curve & Drawdown</div>
            <ResponsiveContainer width="100%" height={180}>
              <ComposedChart data={r.equity_curve} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <XAxis dataKey="timestamp" tick={false} />
                <YAxis yAxisId="pnl" tick={{ fontSize: 9, fill: "#5c6370" }} />
                <YAxis yAxisId="dd" orientation="right" tick={{ fontSize: 9, fill: "#5c6370" }} />
                <Tooltip contentStyle={{ backgroundColor: "#0e0e16", border: "1px solid #1c1a28", fontSize: 10 }} />
                <Area yAxisId="dd" type="monotone" dataKey="drawdown" fill="#f43f5e" fillOpacity={0.15} stroke="none" />
                <Line yAxisId="pnl" type="monotone" dataKey="pnl" stroke="#14f195" strokeWidth={1.5} dot={false} />
                <Line yAxisId="pnl" type="monotone" dataKey="high_water" stroke="#9945ff" strokeWidth={1} dot={false} strokeDasharray="3 3" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Hourly Breakdown Heatmap (Phase 3) */}
        {r.hourly_breakdown && (
          <div className="bg-bg-panel/30 border border-border/40 rounded p-3">
            <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">P&L by Hour (UTC)</div>
            <div className="flex gap-px">
              {r.hourly_breakdown.map((h) => {
                const maxPnl = Math.max(...r.hourly_breakdown!.map((x) => Math.abs(x.total_pnl)), 0.0001);
                const intensity = Math.abs(h.total_pnl) / maxPnl;
                const bg = h.total_pnl >= 0
                  ? `rgba(20, 241, 149, ${intensity * 0.4})`
                  : `rgba(244, 63, 94, ${intensity * 0.4})`;
                return (
                  <div
                    key={h.hour}
                    className="flex-1 text-center py-2 text-[9px]"
                    style={{ backgroundColor: bg }}
                    title={`${h.hour}:00 UTC \u2014 ${h.trade_count} trades, ${h.total_pnl >= 0 ? "+" : ""}${h.total_pnl.toFixed(4)} SOL, ${(h.win_rate * 100).toFixed(0)}% win`}
                  >
                    <div className="text-text-secondary">{h.hour}</div>
                    <div className={`font-mono ${h.total_pnl >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                      {h.trade_count > 0 ? (h.total_pnl >= 0 ? "+" : "") + h.total_pnl.toFixed(3) : "\u2014"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {r.warnings && r.warnings.length > 0 && (
          <div className="bg-accent-amber/5 border border-accent-amber/30 rounded p-3">
            <div className="text-[10px] text-accent-amber uppercase tracking-wider mb-1">Warnings</div>
            <ul className="text-[11px] text-text-secondary space-y-1">
              {r.warnings.map((w, i) => (
                <li key={i}>&#x26A0; {w}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Backtest disclaimer — adapts based on whether fill simulation was used */}
        {r.total_trades > 0 && (
          <div className="bg-bg-panel/30 border border-border/40 rounded px-3 py-2 text-[10px] text-text-secondary leading-relaxed">
            {r.fill_stats ? (
              <>
                <span className="text-accent-green font-semibold">Fill simulation active ({r.fill_stats.venue_label}):</span>{" "}
                Results include venue-specific fees ({r.fill_stats.fee_bps} bps), slippage modeling, Jito landing rate
                ({(r.fill_stats.landing_rate_actual * 100).toFixed(0)}% landed), and tip costs.
                {" "}Remaining limitations: slippage uses estimated pool depth (not real-time reserves),
                competition model is stochastic (not game-theoretic), and state staleness is approximated.
              </>
            ) : (
              <>
                <span className="text-accent-amber font-semibold">No fill simulation:</span>{" "}
                Results assume instant execution at detected price with zero slippage, no competing searchers, and perfect fill rates.
                Enable "Realistic fill simulation" to model venue fees, slippage, and Jito landing rates.
                Treat these P&L numbers as a theoretical upper bound.
              </>
            )}
            {" "}Data source: {config.data_file.includes("birdeye") || config.data_file.includes("merged")
              ? "Birdeye aggregated DEX price — actual execution on a single venue may differ."
              : config.data_file.includes("binance")
              ? "Binance CEX candles."
              : "Parquet replay data."}
          </div>
        )}

        {/* Zero-trade explanation */}
        {r.total_trades === 0 && (
          <div className="bg-accent-amber/10 border border-accent-amber/40 rounded p-4 flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-accent-amber">
                No opportunities detected
              </span>
            </div>
            {r.message && (
              <p className="text-xs text-text-secondary">{r.message}</p>
            )}
            <ul className="text-xs text-text-secondary list-disc list-inside space-y-1">
              <li>Try lowering <span className="font-mono text-accent-amber">min_spread_bps</span> — current value is {config.min_spread_bps} bps. Try 5–10 bps to confirm the pipeline is working.</li>
              <li>Try a different strategy — the selected strategy may not match the data format.
                {(config.strategy === "liquidation_detector") && (
                  <span className="block text-accent-red mt-1">Liquidation detector requires lending protocol account state data (Solend, Marginfi health factors) — OHLCV price data from Binance/Birdeye will never trigger liquidation opportunities.</span>
                )}
                {(config.strategy === "multi_pool_arb") && (
                  <span className="block text-accent-red mt-1">Multi-pool arb requires simultaneous state from multiple DEX pools — a single aggregated price feed won't work. Needs pool-specific data.</span>
                )}
              </li>
              <li>Use a different data file — the current file may cover a low-volatility period with few spread opportunities.</li>
            </ul>
          </div>
        )}

        <div className="bg-bg-panel border border-border rounded overflow-hidden">
          <div className="px-3 py-2 border-b border-border">
            <span className="text-[10px] text-text-secondary uppercase tracking-wider">
              Trades ({trades.length.toLocaleString()})
            </span>
          </div>
          <DataTable
            columns={TRADE_COLUMNS}
            data={pagedTrades as unknown as Record<string, unknown>[]}
            sortable
            pagination={
              pageCount > 1
                ? { page, totalPages: pageCount, onPageChange: setPage }
                : undefined
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 flex flex-col gap-4 max-w-xl">
      <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
        Backtest
      </h1>
      <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-text-secondary uppercase tracking-wider">
            Data File
          </label>
          {files.length === 0 ? (
            <div className="text-xs text-text-secondary italic">
              No Parquet files found — upload via the Data page first
            </div>
          ) : (
            <select
              value={config.data_file}
              onChange={(e) => setConfig((c) => ({ ...c, data_file: e.target.value }))}
              className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
            >
              {files.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} ({f.rows.toLocaleString()} rows)
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Multi-asset: extra data files */}
        {files.length > 0 && (
          <div className="flex flex-col gap-2">
            {config.extra_data_files.map((ef, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <select
                  value={ef}
                  onChange={(e) => {
                    const updated = [...config.extra_data_files];
                    updated[idx] = e.target.value;
                    setConfig((c) => ({ ...c, extra_data_files: updated }));
                  }}
                  className="flex-1 bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
                >
                  <option value="">Select extra file...</option>
                  {files
                    .filter((f) => f.name !== config.data_file)
                    .map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.name} ({f.rows.toLocaleString()} rows)
                      </option>
                    ))}
                </select>
                <button
                  onClick={() => {
                    const updated = config.extra_data_files.filter((_, i) => i !== idx);
                    setConfig((c) => ({ ...c, extra_data_files: updated }));
                  }}
                  className="p-1 text-accent-red/70 hover:text-accent-red transition-colors"
                  title="Remove dataset"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
            {config.extra_data_files.length < 5 && (
              <button
                onClick={() =>
                  setConfig((c) => ({
                    ...c,
                    extra_data_files: [...c.extra_data_files, ""],
                  }))
                }
                className="flex items-center gap-1.5 self-start px-2 py-1 text-[10px] text-text-secondary border border-border/40 rounded hover:bg-bg-active/30 transition-colors"
              >
                <Plus size={11} />
                Add Dataset
              </button>
            )}
          </div>
        )}

        {/* Data source cross-check: what's in the file vs what the strategy needs */}
        {(fileSources || strategyInfo) && (
          <div className="flex flex-col gap-2 bg-bg-main/50 rounded p-3 border border-border/40">
            {/* What the dataset contains */}
            {fileSources && fileSources.sources.length > 0 && (
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-text-secondary uppercase tracking-wider">
                  Dataset contains {fileSources.sources.length > 1 && !strategyInfo?.needs_dual_source ? "— select which to use" : ""}
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {fileSources.sources.map((s, i) => {
                    const sourceKey = s.type;
                    const isSelected = config.use_sources.length === 0 || config.use_sources.includes(sourceKey);
                    const canToggle = fileSources.sources.length > 1 && !strategyInfo?.needs_dual_source;
                    return (
                      <label
                        key={i}
                        className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border cursor-pointer select-none transition-colors ${
                          isSelected
                            ? "bg-accent-green/10 border-accent-green/30 text-accent-green"
                            : "bg-bg-panel/30 border-border/40 text-text-secondary opacity-50"
                        } ${canToggle ? "hover:opacity-80" : ""}`}
                      >
                        {canToggle && (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => {
                              setConfig((c) => {
                                let next = c.use_sources.length === 0
                                  ? fileSources.sources.map(x => x.type)
                                  : [...c.use_sources];
                                if (next.includes(sourceKey)) {
                                  next = next.filter(x => x !== sourceKey);
                                } else {
                                  next.push(sourceKey);
                                }
                                // If all selected, clear to mean "all"
                                if (next.length === fileSources.sources.length) next = [];
                                return { ...c, use_sources: next };
                              });
                            }}
                            className="accent-accent-green w-3 h-3"
                          />
                        )}
                        {s.venue} ({s.type.toUpperCase()})
                      </label>
                    );
                  })}
                  {fileSources.merged && (
                    <span className="text-[10px] px-2 py-0.5 bg-accent-indigo/10 border border-accent-indigo/30 text-accent-indigo rounded">
                      merged + lag-corrected
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* What the strategy requires */}
            {strategyInfo && (
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-text-secondary uppercase tracking-wider">Strategy requires</span>
                <div className="flex flex-wrap gap-1.5">
                  {strategyInfo.needs_dex && (
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${
                      fileSources?.sources.some(s => s.type === "dex")
                        ? "bg-accent-green/10 border-accent-green/30 text-accent-green"
                        : "bg-accent-red/10 border-accent-red/30 text-accent-red"
                    }`}>
                      {fileSources?.sources.some(s => s.type === "dex") ? "✓" : "✗"} DEX price feed
                    </span>
                  )}
                  {strategyInfo.needs_cex && (
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${
                      fileSources?.sources.some(s => s.type === "cex") || config.cex_data_file
                        ? "bg-accent-green/10 border-accent-green/30 text-accent-green"
                        : "bg-accent-red/10 border-accent-red/30 text-accent-red"
                    }`}>
                      {fileSources?.sources.some(s => s.type === "cex") || config.cex_data_file ? "✓" : "✗"} CEX price feed
                    </span>
                  )}
                  {!strategyInfo.needs_cex && !strategyInfo.needs_dex && (
                    <span className="text-[10px] px-2 py-0.5 bg-accent-green/10 border border-accent-green/30 text-accent-green rounded">
                      ✓ Any price data
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* CEX file selector — only when strategy needs CEX and dataset doesn't have it */}
            {strategyInfo?.needs_cex &&
             !fileSources?.sources.some(s => s.type === "cex") && (
              <div className="flex flex-col gap-1.5 mt-1">
                <label className="text-[10px] text-text-secondary">
                  Add CEX Data File
                </label>
                <select
                  value={config.cex_data_file}
                  onChange={(e) => setConfig((c) => ({ ...c, cex_data_file: e.target.value }))}
                  className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
                >
                  <option value="">Select a CEX file...</option>
                  {files.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name} ({f.rows.toLocaleString()} rows)
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-text-secondary uppercase tracking-wider">
            Strategy
          </label>
          <select
            value={config.strategy}
            onChange={(e) => setConfig((c) => ({ ...c, strategy: e.target.value }))}
            className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
          >
            {strategies.map((s) => (
              <option key={s.path} value={s.path}>
                {s.name}
                {s.type === "example" ? " (example)" : s.type === "user" ? " (custom)" : ""}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] text-text-secondary uppercase tracking-wider">
              Min Spread (bps)
            </label>
            <input
              type="number"
              value={config.min_spread_bps}
              onChange={(e) =>
                setConfig((c) => ({ ...c, min_spread_bps: Number(e.target.value) }))
              }
              className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono"
            />
            <span className="text-[9px] text-text-secondary">Trigger when spread exceeds this (after fees)</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] text-text-secondary uppercase tracking-wider">
              Fee (bps)
            </label>
            <input
              type="number"
              value={config.fee_bps}
              onChange={(e) =>
                setConfig((c) => ({ ...c, fee_bps: Number(e.target.value) }))
              }
              className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono"
            />
            <span className="text-[9px] text-text-secondary">DEX swap cost (Raydium=30, optimized routing=5-10)</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] text-text-secondary uppercase tracking-wider">
              Position Size (SOL)
            </label>
            <input
              type="number"
              step="0.01"
              value={config.position_size_sol}
              onChange={(e) =>
                setConfig((c) => ({ ...c, position_size_sol: Number(e.target.value) }))
              }
              className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono"
            />
          </div>
          <div className="flex flex-col gap-1.5 justify-end">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.simulate_before_execute}
                onChange={(e) =>
                  setConfig((c) => ({
                    ...c,
                    simulate_before_execute: e.target.checked,
                  }))
                }
                className="accent-accent-indigo"
              />
              <span className="text-xs text-text-secondary">Simulate before execute</span>
            </label>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-text-secondary uppercase tracking-wider">
            Execution Venue
          </label>
          <select
            value={config.venue}
            onChange={(e) => setConfig((c) => ({ ...c, venue: e.target.value }))}
            className="bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
          >
            <optgroup label="DEX (on-chain, Jito bundle)">
              <option value="raydium">Raydium AMM (25 bps, ~40% Jito landing)</option>
              <option value="orca">Orca Whirlpool (30 bps, ~40% Jito landing)</option>
              <option value="jupiter">Jupiter Aggregated (0+25 bps venue, ~45% landing)</option>
              <option value="aggregated">DEX Aggregated (25 bps, ~40% landing)</option>
            </optgroup>
            <optgroup label="CEX (order book)">
              <option value="binance">Binance (10 bps taker, ~98% fill, 50ms)</option>
              <option value="coinbase">Coinbase (18 bps taker, ~97% fill, 80ms)</option>
            </optgroup>
          </select>
          <span className="text-[9px] text-text-secondary">Simulates venue-specific slippage, fees, and Jito landing rate</span>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={config.simulate_fills}
            onChange={(e) => setConfig((c) => ({ ...c, simulate_fills: e.target.checked }))}
            className="accent-accent-indigo"
          />
          <span className="text-xs text-text-secondary">Realistic fill simulation (slippage + landing rate)</span>
        </label>

        <button
          onClick={handleStart}
          disabled={
            !config.data_file ||
            (strategyInfo?.needs_cex === true &&
             !fileSources?.sources.some(s => s.type === "cex") &&
             !config.cex_data_file)
          }
          className="flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Play size={12} />
          Run Backtest
        </button>
        {strategyInfo?.needs_cex &&
         !fileSources?.sources.some(s => s.type === "cex") &&
         !config.cex_data_file && (
          <p className="text-[10px] text-accent-red text-center">
            Missing CEX data — select a merged dataset or add a CEX file above
          </p>
        )}
      </div>

      {/* ── Parameter Sweep Panel (Phase 4) ── */}
      <div className="bg-bg-panel border border-border rounded overflow-hidden">
        <button
          onClick={() => setSweepOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 hover:bg-bg-active/30 transition-colors"
        >
          <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold flex items-center gap-1.5">
            <Search size={11} />
            Parameter Sweep
          </span>
          {sweepOpen ? (
            <ChevronUp size={13} className="text-text-secondary" />
          ) : (
            <ChevronDown size={13} className="text-text-secondary" />
          )}
        </button>

        {sweepOpen && (
          <div className="border-t border-border p-3 flex flex-col gap-3">
            <p className="text-[10px] text-text-secondary">
              Grid search across parameter ranges. Each combination runs a full backtest.
            </p>

            {/* Param range inputs */}
            {Object.entries(sweepParams).map(([key, p]) => (
              <div key={key} className="flex items-end gap-2">
                <span className="text-[10px] text-text-secondary w-28 shrink-0 font-mono">{key}</span>
                <div className="flex flex-col gap-0.5">
                  <span className="text-[9px] text-text-secondary">Min</span>
                  <input
                    type="number"
                    step="any"
                    value={p.min}
                    onChange={(e) =>
                      setSweepParams((s) => ({ ...s, [key]: { ...s[key], min: Number(e.target.value) } }))
                    }
                    className="bg-bg-main border border-border rounded px-1.5 py-1 text-[11px] font-mono text-text-primary w-16 focus:outline-none focus:border-accent-indigo"
                  />
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-[9px] text-text-secondary">Max</span>
                  <input
                    type="number"
                    step="any"
                    value={p.max}
                    onChange={(e) =>
                      setSweepParams((s) => ({ ...s, [key]: { ...s[key], max: Number(e.target.value) } }))
                    }
                    className="bg-bg-main border border-border rounded px-1.5 py-1 text-[11px] font-mono text-text-primary w-16 focus:outline-none focus:border-accent-indigo"
                  />
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-[9px] text-text-secondary">Step</span>
                  <input
                    type="number"
                    step="any"
                    value={p.step}
                    onChange={(e) =>
                      setSweepParams((s) => ({ ...s, [key]: { ...s[key], step: Number(e.target.value) } }))
                    }
                    className="bg-bg-main border border-border rounded px-1.5 py-1 text-[11px] font-mono text-text-primary w-16 focus:outline-none focus:border-accent-indigo"
                  />
                </div>
                <span className="text-[9px] text-text-secondary whitespace-nowrap">
                  {generateSweepValues(p).length} vals
                </span>
              </div>
            ))}

            <div className="text-[10px] text-text-secondary">
              Total combinations: <span className="font-mono text-text-primary font-bold">{sweepTotalCombinations()}</span>
            </div>

            {/* Walk-Forward toggle */}
            <div className="flex flex-col gap-2 bg-bg-main/50 rounded p-2 border border-border/40">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={walkForward}
                  onChange={(e) => setWalkForward(e.target.checked)}
                  className="accent-accent-indigo"
                />
                <span className="text-xs text-text-secondary flex items-center gap-1">
                  <FlaskConical size={11} />
                  Walk-Forward Validation
                </span>
              </label>
              {walkForward && (
                <div className="flex items-center gap-2 pl-5">
                  <span className="text-[10px] text-text-secondary">Train/Test split:</span>
                  <input
                    type="range"
                    min={0.5}
                    max={0.9}
                    step={0.05}
                    value={trainPct}
                    onChange={(e) => setTrainPct(Number(e.target.value))}
                    className="flex-1 accent-accent-indigo h-1"
                  />
                  <span className="text-[10px] font-mono text-text-primary w-14">
                    {Math.round(trainPct * 100)}/{Math.round((1 - trainPct) * 100)}
                  </span>
                </div>
              )}
            </div>

            <button
              onClick={handleStartSweep}
              disabled={!config.data_file || sweepStatus.state === "running"}
              className="flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold bg-accent-amber/20 border border-accent-amber/50 text-accent-amber rounded hover:bg-accent-amber/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Search size={12} />
              {walkForward ? "Run Walk-Forward" : "Run Sweep"} ({sweepTotalCombinations()} combos)
            </button>

            {/* Sweep progress */}
            {sweepStatus.state === "running" && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-accent-amber animate-pulse" />
                  <span className="text-[11px] font-mono text-accent-amber">
                    Running {sweepStatus.progress}/{sweepStatus.total}...
                  </span>
                </div>
                <div className="w-full h-1.5 bg-bg-main rounded-full overflow-hidden">
                  <div
                    className="h-full bg-accent-amber rounded-full transition-all"
                    style={{ width: `${sweepStatus.total > 0 ? (sweepStatus.progress / sweepStatus.total) * 100 : 0}%` }}
                  />
                </div>
                {sweepStatus.current_params && (
                  <div className="text-[9px] text-text-secondary font-mono">
                    Current: {JSON.stringify(sweepStatus.current_params)}
                  </div>
                )}
              </div>
            )}

            {/* Sweep results */}
            {sweepStatus.state === "completed" && sweepStatus.results && sweepStatus.results.length > 0 && (
              <div className="flex flex-col gap-2">
                {/* Check if this is a walk-forward result */}
                {(sweepStatus.results[0] as unknown as WalkForwardResult)?.type === "walk_forward" ? (
                  (() => {
                    const wf = sweepStatus.results[0] as unknown as WalkForwardResult;
                    return (
                      <div className="flex flex-col gap-2">
                        <div className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
                          Walk-Forward Results
                        </div>
                        {wf.overfit_warning && (
                          <div className="bg-accent-red/10 border border-accent-red/30 rounded px-2 py-1.5 text-[10px] text-accent-red">
                            Overfit warning: in-sample Sharpe is {">"}2x out-of-sample. Results may not generalize.
                          </div>
                        )}
                        <div className="grid grid-cols-2 gap-2">
                          <div className="bg-bg-main/50 rounded p-2 border border-border/40">
                            <div className="text-[9px] text-text-secondary uppercase mb-1">
                              In-Sample ({wf.train_rows.toLocaleString()} rows, {Math.round(wf.train_pct * 100)}%)
                            </div>
                            <div className="grid grid-cols-2 gap-1 text-[10px]">
                              <div>
                                <span className="text-text-secondary">Trades</span>
                                <span className="block font-mono text-text-primary">{wf.in_sample.trades}</span>
                              </div>
                              <div>
                                <span className="text-text-secondary">Sharpe</span>
                                <span className="block font-mono text-accent-green">{wf.in_sample.sharpe.toFixed(2)}</span>
                              </div>
                              <div>
                                <span className="text-text-secondary">P&L</span>
                                <span className={`block font-mono ${wf.in_sample.profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                                  {wf.in_sample.profit_sol >= 0 ? "+" : ""}{wf.in_sample.profit_sol.toFixed(4)}
                                </span>
                              </div>
                              <div>
                                <span className="text-text-secondary">Drawdown</span>
                                <span className="block font-mono text-accent-red">{wf.in_sample.drawdown.toFixed(4)}</span>
                              </div>
                            </div>
                          </div>
                          <div className="bg-bg-main/50 rounded p-2 border border-border/40">
                            <div className="text-[9px] text-text-secondary uppercase mb-1">
                              Out-of-Sample ({wf.test_rows.toLocaleString()} rows, {Math.round((1 - wf.train_pct) * 100)}%)
                            </div>
                            <div className="grid grid-cols-2 gap-1 text-[10px]">
                              <div>
                                <span className="text-text-secondary">Trades</span>
                                <span className="block font-mono text-text-primary">{wf.out_of_sample.trades}</span>
                              </div>
                              <div>
                                <span className="text-text-secondary">Sharpe</span>
                                <span className={`block font-mono ${wf.out_of_sample.sharpe >= wf.in_sample.sharpe * 0.5 ? "text-accent-green" : "text-accent-red"}`}>
                                  {wf.out_of_sample.sharpe.toFixed(2)}
                                </span>
                              </div>
                              <div>
                                <span className="text-text-secondary">P&L</span>
                                <span className={`block font-mono ${wf.out_of_sample.profit_sol >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                                  {wf.out_of_sample.profit_sol >= 0 ? "+" : ""}{wf.out_of_sample.profit_sol.toFixed(4)}
                                </span>
                              </div>
                              <div>
                                <span className="text-text-secondary">Drawdown</span>
                                <span className="block font-mono text-accent-red">{wf.out_of_sample.drawdown.toFixed(4)}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="text-[10px] text-text-secondary">
                          Best params: <span className="font-mono text-text-primary">{JSON.stringify(wf.best_params)}</span>
                        </div>
                        <button
                          onClick={() => handleUseBestParams(wf.best_params)}
                          className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-[11px] bg-accent-green/10 border border-accent-green/40 text-accent-green rounded hover:bg-accent-green/20 transition-colors"
                        >
                          Use Best Params
                        </button>
                      </div>
                    );
                  })()
                ) : (
                  <>
                    <div className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
                      Sweep Results ({(sweepStatus.results as SweepResultRow[]).length} combinations)
                    </div>
                    <div className="overflow-x-auto max-h-64 overflow-y-auto">
                      <table className="w-full text-[10px]">
                        <thead>
                          <tr className="text-text-secondary border-b border-border/40">
                            <th className="text-left py-1 px-1">#</th>
                            {Object.keys((sweepStatus.results as SweepResultRow[])[0]?.params ?? {}).map((k) => (
                              <th key={k} className="text-left py-1 px-1 font-mono">{k}</th>
                            ))}
                            <th className="text-right py-1 px-1">Trades</th>
                            <th className="text-right py-1 px-1">P&L</th>
                            <th className="text-right py-1 px-1">Win%</th>
                            <th className="text-right py-1 px-1">Sharpe</th>
                            <th className="text-right py-1 px-1">Drawdown</th>
                            <th className="text-right py-1 px-1">PF</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(sweepStatus.results as SweepResultRow[]).map((row, i) => (
                            <tr
                              key={i}
                              className={`border-b border-border/20 ${i === 0 ? "bg-accent-green/5" : ""}`}
                            >
                              <td className="py-1 px-1 text-text-secondary">{i + 1}</td>
                              {Object.values(row.params).map((v, j) => (
                                <td key={j} className="py-1 px-1 font-mono text-text-primary">{v}</td>
                              ))}
                              <td className="text-right py-1 px-1 font-mono">{row.total_trades}</td>
                              <td className={`text-right py-1 px-1 font-mono ${(row.total_profit_sol ?? 0) >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                                {(row.total_profit_sol ?? 0) >= 0 ? "+" : ""}{(row.total_profit_sol ?? 0).toFixed(4)}
                              </td>
                              <td className="text-right py-1 px-1 font-mono">
                                {((row.win_rate ?? 0) * 100).toFixed(0)}%
                              </td>
                              <td className={`text-right py-1 px-1 font-mono font-bold ${(row.sharpe_ratio ?? 0) > 1 ? "text-accent-green" : (row.sharpe_ratio ?? 0) > 0 ? "text-accent-amber" : "text-accent-red"}`}>
                                {(row.sharpe_ratio ?? 0).toFixed(2)}
                              </td>
                              <td className="text-right py-1 px-1 font-mono text-accent-red">
                                {(row.max_drawdown_sol ?? 0).toFixed(4)}
                              </td>
                              <td className="text-right py-1 px-1 font-mono">
                                {(row.profit_factor ?? 0) > 100 ? "\u221E" : (row.profit_factor ?? 0).toFixed(1)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {(sweepStatus.results as SweepResultRow[])[0] && !(sweepStatus.results as SweepResultRow[])[0].error && (
                      <button
                        onClick={() => handleUseBestParams((sweepStatus.results as SweepResultRow[])[0].params)}
                        className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-[11px] bg-accent-green/10 border border-accent-green/40 text-accent-green rounded hover:bg-accent-green/20 transition-colors"
                      >
                        Use Best Params (Sharpe {(sweepStatus.results as SweepResultRow[])[0].sharpe_ratio.toFixed(2)})
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Recent Runs */}
      <div className="bg-bg-panel border border-border rounded overflow-hidden">
        <button
          onClick={() => setHistoryOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 hover:bg-bg-active/30 transition-colors"
        >
          <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Recent Runs ({history.length})
          </span>
          <div className="flex items-center gap-2">
            {history.length > 0 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleClearHistory();
                }}
                className="flex items-center gap-1 px-2 py-0.5 text-[10px] text-accent-red/70 hover:text-accent-red border border-accent-red/20 rounded transition-colors"
              >
                <Trash2 size={10} />
                Clear
              </button>
            )}
            {historyOpen ? (
              <ChevronUp size={13} className="text-text-secondary" />
            ) : (
              <ChevronDown size={13} className="text-text-secondary" />
            )}
          </div>
        </button>

        {historyOpen && (
          <div className="border-t border-border">
            {history.length === 0 ? (
              <div className="px-3 py-4 text-xs text-text-secondary italic text-center">
                No runs yet — completed runs will appear here
              </div>
            ) : (
              <div className="divide-y divide-border/40">
                {history.length >= 2 && (
                  <div className="px-3 py-1.5 flex items-center justify-between bg-bg-main/30">
                    <span className="text-[9px] text-text-secondary">
                      Select 2 runs to compare ({compareIds.filter(Boolean).length}/2)
                    </span>
                    {compareIds[0] && compareIds[1] && (
                      <button
                        onClick={() => setCompareOpen(true)}
                        className="flex items-center gap-1 px-2 py-0.5 text-[10px] text-accent-indigo border border-accent-indigo/30 rounded hover:bg-accent-indigo/10 transition-colors"
                      >
                        <GitCompare size={10} />
                        Compare
                      </button>
                    )}
                  </div>
                )}
                {history.map((entry) => (
                  <div
                    key={entry.id}
                    className={`flex items-center gap-2 px-3 py-2.5 hover:bg-bg-active/30 transition-colors ${
                      selectedHistoryId === entry.id ? "bg-accent-indigo/10" : ""
                    }`}
                  >
                    {history.length >= 2 && (
                      <input
                        type="checkbox"
                        checked={compareIds.includes(entry.id)}
                        onChange={() => toggleCompare(entry.id)}
                        className="accent-accent-indigo w-3 h-3 shrink-0"
                        title="Select for comparison"
                      />
                    )}
                    <button
                      onClick={() => handleSelectHistoryRun(entry)}
                      className="flex-1 text-left flex items-center justify-between gap-3 min-w-0"
                    >
                      <div className="flex flex-col gap-0.5 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-text-primary font-mono truncate">
                            {entry.strategy}
                          </span>
                          <span className="text-[10px] text-text-secondary truncate">
                            {entry.data_file}
                          </span>
                        </div>
                        <div className="text-[10px] text-text-secondary">
                          spread{"\u2265"}{entry.min_spread_bps}bps · fee={entry.fee_bps}bps · {entry.position_size_sol}SOL
                          {entry.venue ? ` · ${entry.venue}` : ""}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5 shrink-0">
                        <span
                          className={`text-xs font-mono font-semibold ${
                            entry.total_profit_sol >= 0 ? "text-accent-green" : "text-accent-red"
                          }`}
                        >
                          {entry.total_profit_sol >= 0 ? "+" : ""}
                          {entry.total_profit_sol.toFixed(4)} SOL
                        </span>
                        <span className="text-[10px] text-text-secondary">
                          {entry.total_trades} trades ·{" "}
                          {new Date(entry.timestamp).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Run Comparison Panel (Phase 4) ── */}
      {compareOpen && compareA && compareB && (
        <div className="bg-bg-panel border border-border rounded overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold flex items-center gap-1.5">
              <GitCompare size={11} />
              Run Comparison
            </span>
            <button
              onClick={() => { setCompareOpen(false); setCompareIds([null, null]); }}
              className="text-[10px] text-text-secondary hover:text-text-primary transition-colors"
            >
              Close
            </button>
          </div>
          <div className="p-3">
            <ComparisonTable runA={compareA} runB={compareB} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Comparison Table Component (Phase 4) ── */

function ComparisonTable({ runA, runB }: { runA: RunHistoryEntry; runB: RunHistoryEntry }) {
  const rA = runA.results;
  const rB = runB.results;
  if (!rA || !rB) return null;

  const rows: Array<{ label: string; a: string; b: string; higherIsBetter: boolean }> = [
    { label: "Strategy", a: runA.strategy, b: runB.strategy, higherIsBetter: true },
    { label: "Total Trades", a: String(rA.total_trades), b: String(rB.total_trades), higherIsBetter: true },
    { label: "Total P&L", a: `${rA.total_profit_sol >= 0 ? "+" : ""}${rA.total_profit_sol.toFixed(4)} SOL`, b: `${rB.total_profit_sol >= 0 ? "+" : ""}${rB.total_profit_sol.toFixed(4)} SOL`, higherIsBetter: true },
    { label: "Win Rate", a: `${(rA.win_rate * 100).toFixed(1)}%`, b: `${(rB.win_rate * 100).toFixed(1)}%`, higherIsBetter: true },
    { label: "Avg Spread", a: `${rA.avg_spread_bps.toFixed(1)} bps`, b: `${rB.avg_spread_bps.toFixed(1)} bps`, higherIsBetter: true },
    { label: "Best Trade", a: `${rA.best_trade_sol.toFixed(4)} SOL`, b: `${rB.best_trade_sol.toFixed(4)} SOL`, higherIsBetter: true },
    { label: "Worst Trade", a: `${rA.worst_trade_sol.toFixed(4)} SOL`, b: `${rB.worst_trade_sol.toFixed(4)} SOL`, higherIsBetter: false },
  ];

  if (rA.risk_metrics && rB.risk_metrics) {
    rows.push(
      { label: "Sharpe Ratio", a: rA.risk_metrics.sharpe_ratio.toFixed(2), b: rB.risk_metrics.sharpe_ratio.toFixed(2), higherIsBetter: true },
      { label: "Max Drawdown", a: `${rA.risk_metrics.max_drawdown_sol.toFixed(4)} SOL`, b: `${rB.risk_metrics.max_drawdown_sol.toFixed(4)} SOL`, higherIsBetter: false },
      { label: "Profit Factor", a: rA.risk_metrics.profit_factor > 100 ? "\u221E" : rA.risk_metrics.profit_factor.toFixed(2), b: rB.risk_metrics.profit_factor > 100 ? "\u221E" : rB.risk_metrics.profit_factor.toFixed(2), higherIsBetter: true },
      { label: "Sortino Ratio", a: rA.risk_metrics.sortino_ratio > 100 ? "\u221E" : rA.risk_metrics.sortino_ratio.toFixed(2), b: rB.risk_metrics.sortino_ratio > 100 ? "\u221E" : rB.risk_metrics.sortino_ratio.toFixed(2), higherIsBetter: true },
    );
  }

  function deltaColor(a: string, b: string, higherIsBetter: boolean): [string, string] {
    const numA = parseFloat(a.replace(/[^0-9.\-]/g, ""));
    const numB = parseFloat(b.replace(/[^0-9.\-]/g, ""));
    if (isNaN(numA) || isNaN(numB) || numA === numB) return ["text-text-primary", "text-text-primary"];
    const aWins = higherIsBetter ? numA > numB : numA < numB;
    return aWins
      ? ["text-accent-green", "text-accent-red"]
      : ["text-accent-red", "text-accent-green"];
  }

  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-text-secondary border-b border-border/40">
          <th className="text-left py-1.5 px-1">Metric</th>
          <th className="text-right py-1.5 px-1">
            <span className="font-mono">{runA.strategy}</span>
            <div className="text-[9px] font-normal">
              {new Date(runA.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </div>
          </th>
          <th className="text-right py-1.5 px-1">
            <span className="font-mono">{runB.strategy}</span>
            <div className="text-[9px] font-normal">
              {new Date(runB.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const [colorA, colorB] = deltaColor(row.a, row.b, row.higherIsBetter);
          return (
            <tr key={row.label} className="border-b border-border/20">
              <td className="py-1.5 px-1 text-text-secondary">{row.label}</td>
              <td className={`text-right py-1.5 px-1 font-mono ${colorA}`}>{row.a}</td>
              <td className={`text-right py-1.5 px-1 font-mono ${colorB}`}>{row.b}</td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr className="text-[9px] text-text-secondary">
          <td className="py-1.5 px-1" colSpan={3}>
            Params: A = spread{"\u2265"}{runA.min_spread_bps}bps fee={runA.fee_bps}bps {runA.position_size_sol}SOL
            {" "}| B = spread{"\u2265"}{runB.min_spread_bps}bps fee={runB.fee_bps}bps {runB.position_size_sol}SOL
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
