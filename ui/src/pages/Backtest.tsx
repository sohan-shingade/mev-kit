import { useEffect, useRef, useState } from "react";
import { get, post } from "../api/client";
import type { BacktestStatus, DataFile, TradeRow } from "../api/types";
import DataTable from "../components/common/DataTable";
import { toast } from "../components/common/Toast";
import { Play, Square, RotateCcw, Download, ChevronDown, ChevronUp, Trash2 } from "lucide-react";

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
  strategy: string;
  min_spread_bps: number;
  fee_bps: number;
  position_size_sol: number;
  simulate_before_execute: boolean;
}

interface RunHistoryEntry {
  id: string;
  timestamp: string;
  strategy: string;
  data_file: string;
  min_spread_bps: number;
  fee_bps: number;
  position_size_sol: number;
  total_trades: number;
  total_profit_sol: number;
  results: BacktestStatus["results"];
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
    strategy: "cex_dex_arb",
    min_spread_bps: 20,
    fee_bps: 30,
    position_size_sol: 0.1,
    simulate_before_execute: true,
  });
  const [status, setStatus] = useState<BacktestStatus>({ state: "idle" });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [page, setPage] = useState(1);
  const PER_PAGE = 50;

  // Recent runs history
  const [history, setHistory] = useState<RunHistoryEntry[]>(loadHistory);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);

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
                id: `${Date.now()}`,
                timestamp: new Date().toISOString(),
                strategy: config.strategy,
                data_file: config.data_file,
                min_spread_bps: config.min_spread_bps,
                fee_bps: config.fee_bps,
                position_size_sol: config.position_size_sol,
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
      await post("/api/backtest/start", config);
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
              <li>Try a different strategy — the selected strategy may not match the data format.</li>
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

        <button
          onClick={handleStart}
          disabled={!config.data_file}
          className="flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Play size={12} />
          Run Backtest
        </button>
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
                {history.map((entry) => (
                  <button
                    key={entry.id}
                    onClick={() => handleSelectHistoryRun(entry)}
                    className={`w-full text-left px-3 py-2.5 hover:bg-bg-active/30 transition-colors flex items-center justify-between gap-3 ${
                      selectedHistoryId === entry.id ? "bg-accent-indigo/10" : ""
                    }`}
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
                        spread≥{entry.min_spread_bps}bps · fee={entry.fee_bps}bps · {entry.position_size_sol}SOL
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
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
