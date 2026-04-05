import { useEffect, useState, useCallback, useRef } from "react";
import { get, post, del } from "../api/client";
import type { DataFile } from "../api/types";
import Modal from "../components/common/Modal";
import DataTable from "../components/common/DataTable";
import { toast } from "../components/common/Toast";
import { RefreshCw, Trash2, Eye, Download, Merge } from "lucide-react";

interface PreviewData {
  columns: string[];
  rows: Record<string, unknown>[];
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

interface FetchHistoricalForm {
  pool_address: string;
  interval: string;
  duration: string;
}

interface FetchBinanceForm {
  symbol: string;
  interval: string;
  days: number;
  use_us: boolean;
}

interface FetchBirdeyeForm {
  base_address: string;
  quote_address: string;
  interval: string;
  days: number;
  pair_label: string;
}

interface FetchJob {
  status: "running" | "completed" | "error";
  progress: number;
  total?: number;
  file?: string;
  rows?: number;
  error?: string;
}

interface PrepareForm {
  dex_file: string;
  cex_file: string;
  interval_seconds: number;
  lag: boolean;
}

interface PrepareResult {
  status: string;
  rows?: number;
  time_range_start?: string;
  time_range_end?: string;
  avg_spread_bps?: number;
  max_spread_bps?: number;
  data_gaps_pct?: number;
  lag_applied?: boolean;
  output_path?: string;
  dex_price_range?: string;
  cex_price_range?: string;
  error?: string;
}

const POOL_PRESETS = [
  { label: "SOL/USDC (Raydium)", address: "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2" },
  { label: "SOL/USDT (Raydium)", address: "7XawhbbxtsRcQA8KTkHT9f9nc6d69UwqCDh6U5EEbEmX" },
  { label: "SOL/USDC (Orca Whirlpool)", address: "HJPjoWUrhoZzkNfRpHuieeFk9BcLEjS1rKNhqTUFi2Ba" },
  { label: "mSOL/SOL (Raydium)", address: "EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U" },
  { label: "JitoSOL/SOL (Raydium)", address: "2uoKbPEidR7FBnCHsMPkjRsH4pMtDMgw7f8ickPRPfwK" },
  { label: "RAY/USDC (Raydium)", address: "6UmmUiYoBjSrhakAobJw8BvkmJtDVxaeBtbt7rxWo1mg" },
  { label: "BONK/SOL (Raydium)", address: "BqnpCdDLPV2pFdAaLnVidmn3G93RP2p5oRdGEY2sJGez" },
];

// CEX pairs — match these with Birdeye pairs for CEX-DEX arb backtesting
const BINANCE_PRESETS = [
  { label: "SOL/USDT", symbol: "SOLUSDT" },
  { label: "SOL/USDC", symbol: "SOLUSDC" },
  { label: "ETH/USDT", symbol: "ETHUSDT" },
  { label: "BTC/USDT", symbol: "BTCUSDT" },
  { label: "WIF/USDT", symbol: "WIFUSDT" },
  { label: "JUP/USDT", symbol: "JUPUSDT" },
  { label: "BONK/USDT", symbol: "BONKUSDT" },
  { label: "JTO/USDT", symbol: "JTOUSDT" },
  { label: "RAY/USDT", symbol: "RAYUSDT" },
  { label: "PYTH/USDT", symbol: "PYTHUSDT" },
  { label: "RNDR/USDT", symbol: "RNDRUSDT" },
  { label: "HNT/USDT", symbol: "HNTUSDT" },
];

// DEX pairs — token mint addresses, Birdeye aggregates across all DEXes
// Common mints:
//   SOL:  So11111111111111111111111111111111111111112
//   USDC: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
//   USDT: Es9vMFrzaCERmKfreVDyFe3GHMC3dYTzJ3tEX2s8VdDg
const BIRDEYE_TOKEN_PRESETS = [
  // Stablecoin pairs (highest volume, best for CEX-DEX arb)
  { label: "SOL/USDC", base: "So11111111111111111111111111111111111111112", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  { label: "SOL/USDT", base: "So11111111111111111111111111111111111111112", quote: "Es9vMFrzaCERmKfreVDyFe3GHMC3dYTzJ3tEX2s8VdDg" },
  // Memecoins (high volatility, frequent arb opportunities)
  { label: "WIF/USDC", base: "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  { label: "BONK/SOL", base: "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", quote: "So11111111111111111111111111111111111111112" },
  { label: "BONK/USDC", base: "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  // DeFi tokens
  { label: "JUP/USDC", base: "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  { label: "RAY/USDC", base: "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  { label: "JTO/USDC", base: "jtojtomepa8beP8AuQc6eXt5FriJwfFwwn2LwDeFkt", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  { label: "PYTH/USDC", base: "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" },
  // LST pairs (liquid staking — different arb dynamics)
  { label: "mSOL/SOL", base: "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So", quote: "So11111111111111111111111111111111111111112" },
  { label: "jitoSOL/SOL", base: "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn", quote: "So11111111111111111111111111111111111111112" },
  { label: "bSOL/SOL", base: "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1", quote: "So11111111111111111111111111111111111111112" },
];

export default function Data() {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [fetchingHist, setFetchingHist] = useState(false);
  const [fetchingBinance, setFetchingBinance] = useState(false);
  const [fetchingBirdeye, setFetchingBirdeye] = useState(false);
  const [histForm, setHistForm] = useState<FetchHistoricalForm>({
    pool_address: POOL_PRESETS[0].address,
    interval: "5s",
    duration: "5m",
  });
  const [binanceForm, setBinanceForm] = useState<FetchBinanceForm>({
    symbol: BINANCE_PRESETS[0].symbol,
    interval: "1m",
    days: 7,
    use_us: false,
  });
  const [birdeyeForm, setBirdeyeForm] = useState<FetchBirdeyeForm>({
    base_address: BIRDEYE_TOKEN_PRESETS[0].base,
    quote_address: BIRDEYE_TOKEN_PRESETS[0].quote,
    interval: "15m",
    days: 7,
    pair_label: BIRDEYE_TOKEN_PRESETS[0].label,
  });
  const [fetchJobs, setFetchJobs] = useState<Record<string, FetchJob>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [prepareForm, setPrepareForm] = useState<PrepareForm>({
    dex_file: "",
    cex_file: "",
    interval_seconds: 60,
    lag: true,
  });
  const [preparing, setPreparing] = useState(false);
  const [prepareResult, setPrepareResult] = useState<PrepareResult | null>(null);

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    try {
      const f = await get<DataFile[]>("/api/data/files");
      setFiles(f);
    } catch {
      toast("Failed to load data files", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchJobStatus = useCallback(async () => {
    try {
      const jobs = await get<Record<string, FetchJob>>("/api/data/fetch/status");
      setFetchJobs(jobs);
      // If any job just completed, refresh file list
      const anyCompleted = Object.values(jobs).some((j) => j.status === "completed");
      if (anyCompleted) {
        fetchFiles();
      }
    } catch {
      // silently ignore status poll errors
    }
  }, [fetchFiles]);

  // Start/stop polling based on running jobs
  useEffect(() => {
    const hasRunning = Object.values(fetchJobs).some((j) => j.status === "running");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(fetchJobStatus, 2000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [fetchJobs, fetchJobStatus]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  async function openPreview(name: string) {
    setPreviewFile(name);
    setPreviewData(null);
    setPreviewLoading(true);
    try {
      const data = await get<PreviewData>(`/api/data/files/${name}/preview`);
      setPreviewData(data);
    } catch {
      toast("Failed to load preview", "error");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await del(`/api/data/files/${deleteTarget}`);
      toast(`Deleted ${deleteTarget}`, "success");
      setDeleteTarget(null);
      fetchFiles();
    } catch {
      toast("Failed to delete file", "error");
    } finally {
      setDeleting(false);
    }
  }

  async function handleFetchHistorical() {
    if (!histForm.pool_address.trim()) {
      toast("Enter a pool address", "warning");
      return;
    }
    setFetchingHist(true);
    try {
      const result = await post<{ status: string; job_id?: string; error?: string }>(
        "/api/data/fetch/historical",
        histForm
      );
      if (result.status === "error") {
        toast(result.error ?? "Fetch failed", "error");
      } else {
        toast("Historical fetch started", "success");
        // Kick off first status poll immediately
        fetchJobStatus();
        if (!pollRef.current) {
          pollRef.current = setInterval(fetchJobStatus, 2000);
        }
      }
    } catch {
      toast("Failed to start historical fetch", "error");
    } finally {
      setFetchingHist(false);
    }
  }

  async function handleFetchBinance() {
    if (!binanceForm.symbol.trim()) {
      toast("Enter a symbol", "warning");
      return;
    }
    setFetchingBinance(true);
    try {
      const result = await post<{ status: string; job_id?: string; error?: string }>(
        "/api/data/fetch/binance",
        binanceForm
      );
      if (result.status === "error") {
        toast(result.error ?? "Fetch failed", "error");
      } else {
        toast("Binance fetch started", "success");
        fetchJobStatus();
        if (!pollRef.current) {
          pollRef.current = setInterval(fetchJobStatus, 2000);
        }
      }
    } catch {
      toast("Failed to start Binance fetch", "error");
    } finally {
      setFetchingBinance(false);
    }
  }

  async function handleFetchBirdeye() {
    if (!birdeyeForm.base_address.trim() || !birdeyeForm.quote_address.trim()) {
      toast("Enter base and quote addresses", "warning");
      return;
    }
    setFetchingBirdeye(true);
    try {
      const result = await post<{ status: string; job_id?: string; error?: string }>(
        "/api/data/fetch/birdeye",
        birdeyeForm
      );
      if (result.status === "error") {
        toast(result.error ?? "Fetch failed", "error");
      } else {
        toast("Birdeye fetch started", "success");
        fetchJobStatus();
        if (!pollRef.current) {
          pollRef.current = setInterval(fetchJobStatus, 2000);
        }
      }
    } catch {
      toast("Failed to start Birdeye fetch", "error");
    } finally {
      setFetchingBirdeye(false);
    }
  }

  async function handlePrepareData() {
    if (!prepareForm.dex_file || !prepareForm.cex_file) {
      toast("Select both DEX and CEX data files", "warning");
      return;
    }
    setPreparing(true);
    setPrepareResult(null);
    try {
      const result = await post<PrepareResult>("/api/data/prepare", prepareForm);
      setPrepareResult(result);
      if (result.status === "completed" && result.rows && result.rows > 0) {
        toast(`Merged ${result.rows} rows`, "success");
        fetchFiles();
      } else if (result.error) {
        toast(result.error, "error");
      }
    } catch {
      toast("Failed to prepare data", "error");
    } finally {
      setPreparing(false);
    }
  }

  const parquetFiles = files.filter((f) => f.name.endsWith(".parquet"));

  const previewColumns = previewData
    ? previewData.columns.map((c) => ({ key: c, label: c }))
    : [];

  const inputCls =
    "bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono";

  const jobEntries = Object.entries(fetchJobs);

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Data Files
        </h1>
        <button
          onClick={fetchFiles}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1 text-xs bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors disabled:opacity-40"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <div className="bg-bg-panel border border-border rounded overflow-hidden">
        {loading && files.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">Loading…</div>
        ) : files.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            No data files found. Use the fetch forms below to download historical data.
          </div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Name</th>
                <th className="text-left px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Size</th>
                <th className="text-left px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Rows</th>
                <th className="text-left px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Modified</th>
                <th className="text-left px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Columns</th>
                <th className="text-right px-3 py-1.5 text-[10px] text-text-secondary uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.name} className="border-b border-border/40 hover:bg-bg-panel/50">
                  <td className="px-3 py-1.5 font-mono text-text-primary">{f.name}</td>
                  <td className="px-3 py-1.5 font-mono text-text-secondary">{formatBytes(f.size_bytes)}</td>
                  <td className="px-3 py-1.5 font-mono text-text-primary">{f.rows.toLocaleString()}</td>
                  <td className="px-3 py-1.5 font-mono text-text-secondary">{formatDate(f.modified)}</td>
                  <td className="px-3 py-1.5 text-text-secondary max-w-[200px] truncate" title={f.columns.join(", ")}>
                    {f.columns.slice(0, 4).join(", ")}
                    {f.columns.length > 4 ? ` +${f.columns.length - 4}` : ""}
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-1.5 justify-end">
                      <button
                        onClick={() => openPreview(f.name)}
                        title="Preview"
                        className="p-1 text-text-secondary hover:text-accent-indigo transition-colors"
                      >
                        <Eye size={13} />
                      </button>
                      <button
                        onClick={() => {
                          const a = document.createElement("a");
                          a.href = `/api/data/files/${f.name}/download`;
                          a.download = f.name;
                          a.click();
                        }}
                        title="Download"
                        className="p-1 text-text-secondary hover:text-accent-green transition-colors"
                      >
                        <Download size={13} />
                      </button>
                      <button
                        onClick={() => setDeleteTarget(f.name)}
                        title="Delete"
                        className="p-1 text-text-secondary hover:text-accent-red transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Fetch Historical (Raydium) */}
        <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-3">
          <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Fetch Historical (Raydium)
          </h2>
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Pool Preset</label>
              <select
                value={histForm.pool_address}
                onChange={(e) => setHistForm((f) => ({ ...f, pool_address: e.target.value }))}
                className={inputCls}
              >
                {POOL_PRESETS.map((p) => (
                  <option key={p.address} value={p.address}>{p.label}</option>
                ))}
                <option value="">Custom…</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Pool Address</label>
              <input
                type="text"
                value={histForm.pool_address}
                onChange={(e) => setHistForm((f) => ({ ...f, pool_address: e.target.value }))}
                placeholder="e.g. 58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Poll Interval</label>
                <select
                  value={histForm.interval}
                  onChange={(e) => setHistForm((f) => ({ ...f, interval: e.target.value }))}
                  className={inputCls}
                >
                  {[
                    { v: "5s", l: "5 seconds" },
                    { v: "10s", l: "10 seconds" },
                    { v: "30s", l: "30 seconds" },
                    { v: "1m", l: "1 minute" },
                    { v: "5m", l: "5 minutes" },
                  ].map((i) => (
                    <option key={i.v} value={i.v}>{i.l}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Duration</label>
                <select
                  value={histForm.duration}
                  onChange={(e) => setHistForm((f) => ({ ...f, duration: e.target.value }))}
                  className={inputCls}
                >
                  {[
                    { v: "1m", l: "1 minute" },
                    { v: "5m", l: "5 minutes" },
                    { v: "15m", l: "15 minutes" },
                    { v: "30m", l: "30 minutes" },
                    { v: "1h", l: "1 hour" },
                  ].map((d) => (
                    <option key={d.v} value={d.v}>{d.l}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="text-[10px] text-accent-amber border border-accent-amber/30 rounded px-2 py-1.5 bg-accent-amber/5">
              Live polling — fetches current on-chain state at each interval. Runs in real-time (5 min duration = 5 min to complete). For bulk historical data, use Binance fetch instead.
            </div>
          </div>
          <button
            onClick={handleFetchHistorical}
            disabled={fetchingHist}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
          >
            {fetchingHist ? "Fetching…" : "Fetch Historical Data"}
          </button>
        </div>

        {/* Fetch Binance OHLCV */}
        <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-3">
          <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Fetch Binance OHLCV
          </h2>
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Symbol Preset</label>
              <select
                value={binanceForm.symbol}
                onChange={(e) => setBinanceForm((f) => ({ ...f, symbol: e.target.value }))}
                className={inputCls}
              >
                {BINANCE_PRESETS.map((p) => (
                  <option key={p.symbol} value={p.symbol}>{p.label}</option>
                ))}
                <option value="">Custom…</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Symbol</label>
              <input
                type="text"
                value={binanceForm.symbol}
                onChange={(e) => setBinanceForm((f) => ({ ...f, symbol: e.target.value }))}
                placeholder="e.g. SOLUSDT"
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Interval</label>
                <select
                  value={binanceForm.interval}
                  onChange={(e) => setBinanceForm((f) => ({ ...f, interval: e.target.value }))}
                  className={inputCls}
                >
                  {["1s", "1m", "5m", "15m", "1h", "4h", "1d"].map((i) => (
                    <option key={i} value={i}>{i}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Days</label>
                <input
                  type="number"
                  value={binanceForm.days}
                  onChange={(e) =>
                    setBinanceForm((f) => ({ ...f, days: Number(e.target.value) }))
                  }
                  min={1}
                  max={365}
                  className={inputCls}
                />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={binanceForm.use_us}
                onChange={(e) => setBinanceForm((f) => ({ ...f, use_us: e.target.checked }))}
                className="accent-accent-indigo"
              />
              Use Binance US endpoint
            </label>
            <span className="text-[10px] text-text-secondary italic">
              {binanceForm.use_us ? "api.binance.us" : "api.binance.com"}
            </span>
          </div>
          <button
            onClick={handleFetchBinance}
            disabled={fetchingBinance}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-amber/20 border border-accent-amber/50 text-accent-amber rounded hover:bg-accent-amber/30 disabled:opacity-40 transition-colors"
          >
            {fetchingBinance ? "Fetching…" : "Fetch Binance Data"}
          </button>
        </div>

        {/* Fetch Birdeye DEX OHLCV */}
        <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-3">
          <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Fetch Birdeye DEX OHLCV
          </h2>
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Pair Preset</label>
              <select
                value={birdeyeForm.pair_label}
                onChange={(e) => {
                  const preset = BIRDEYE_TOKEN_PRESETS.find((p) => p.label === e.target.value);
                  if (preset) {
                    setBirdeyeForm((f) => ({
                      ...f,
                      pair_label: preset.label,
                      base_address: preset.base,
                      quote_address: preset.quote,
                    }));
                  } else {
                    setBirdeyeForm((f) => ({ ...f, pair_label: e.target.value }));
                  }
                }}
                className={inputCls}
              >
                {BIRDEYE_TOKEN_PRESETS.map((p) => (
                  <option key={p.label} value={p.label}>{p.label}</option>
                ))}
                <option value="">Custom…</option>
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Base Address</label>
              <input
                type="text"
                value={birdeyeForm.base_address}
                onChange={(e) => setBirdeyeForm((f) => ({ ...f, base_address: e.target.value }))}
                placeholder="e.g. So11111111111111111111111111111111111111112"
                className={inputCls}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-text-secondary">Quote Address</label>
              <input
                type="text"
                value={birdeyeForm.quote_address}
                onChange={(e) => setBirdeyeForm((f) => ({ ...f, quote_address: e.target.value }))}
                placeholder="e.g. EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                className={inputCls}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Interval</label>
                <select
                  value={birdeyeForm.interval}
                  onChange={(e) => setBirdeyeForm((f) => ({ ...f, interval: e.target.value }))}
                  className={inputCls}
                >
                  {["1m", "5m", "15m", "1H", "4H", "1D"].map((i) => (
                    <option key={i} value={i}>{i}</option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-text-secondary">Days</label>
                <input
                  type="number"
                  value={birdeyeForm.days}
                  onChange={(e) =>
                    setBirdeyeForm((f) => ({ ...f, days: Number(e.target.value) }))
                  }
                  min={1}
                  max={30}
                  className={inputCls}
                />
              </div>
            </div>
            <div className="text-[10px] text-accent-green border border-accent-green/30 rounded px-2 py-1.5 bg-accent-green/5">
              Historical on-chain prices from Birdeye (free tier: 750 calls/month)
            </div>
          </div>
          <button
            onClick={handleFetchBirdeye}
            disabled={fetchingBirdeye}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-green/20 border border-accent-green/50 text-accent-green rounded hover:bg-accent-green/30 disabled:opacity-40 transition-colors"
          >
            {fetchingBirdeye ? "Fetching…" : "Fetch DEX History"}
          </button>
        </div>
      </div>

      {/* Fetch Job Status */}
      {jobEntries.length > 0 && (
        <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-3">
          <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Fetch Jobs
          </h2>
          <div className="flex flex-col gap-2">
            {jobEntries.map(([id, job]) => {
              const pct =
                job.total && job.total > 0
                  ? Math.min(100, Math.round((job.progress / job.total) * 100))
                  : job.status === "completed"
                  ? 100
                  : 0;

              return (
                <div key={id} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[10px] text-text-secondary truncate max-w-[60%]">
                      {id}
                    </span>
                    <span
                      className={`text-[10px] font-semibold ${
                        job.status === "completed"
                          ? "text-accent-green"
                          : job.status === "error"
                          ? "text-accent-red"
                          : "text-accent-amber"
                      }`}
                    >
                      {job.status === "running"
                        ? `${job.progress}${job.total ? ` / ${job.total}` : ""} rows`
                        : job.status === "completed"
                        ? `done · ${job.rows?.toLocaleString() ?? 0} rows${job.file ? ` · ${job.file}` : ""}`
                        : job.error ?? "error"}
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-bg-main overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        job.status === "error"
                          ? "bg-accent-red"
                          : job.status === "completed"
                          ? "bg-accent-green"
                          : "bg-accent-amber"
                      }`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Prepare Backtest Data */}
      <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-3">
        <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
          Prepare Backtest Data
        </h2>
        <p className="text-[10px] text-text-secondary leading-relaxed">
          Merges DEX and CEX data into a single time-aligned dataset. Lagged mode uses the previous
          candle's price to prevent lookahead bias.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-text-secondary">DEX Data</label>
            <select
              value={prepareForm.dex_file}
              onChange={(e) => setPrepareForm((f) => ({ ...f, dex_file: e.target.value }))}
              className={inputCls}
            >
              <option value="">Select DEX file...</option>
              {parquetFiles.map((f) => (
                <option key={f.name} value={f.name}>{f.name}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-text-secondary">CEX Data</label>
            <select
              value={prepareForm.cex_file}
              onChange={(e) => setPrepareForm((f) => ({ ...f, cex_file: e.target.value }))}
              className={inputCls}
            >
              <option value="">Select CEX file...</option>
              {parquetFiles.map((f) => (
                <option key={f.name} value={f.name}>{f.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-text-secondary">Interval</label>
            <select
              value={prepareForm.interval_seconds}
              onChange={(e) =>
                setPrepareForm((f) => ({ ...f, interval_seconds: Number(e.target.value) }))
              }
              className={inputCls}
            >
              <option value={60}>60s (1m candles)</option>
              <option value={300}>300s (5m candles)</option>
              <option value={900}>900s (15m candles)</option>
              <option value={3600}>3600s (1h candles)</option>
            </select>
          </div>
          <div className="flex items-end pb-0.5">
            <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={prepareForm.lag}
                onChange={(e) => setPrepareForm((f) => ({ ...f, lag: e.target.checked }))}
                className="accent-accent-indigo"
              />
              Apply lag (prevent lookahead bias)
            </label>
          </div>
        </div>
        <button
          onClick={handlePrepareData}
          disabled={preparing || !prepareForm.dex_file || !prepareForm.cex_file}
          className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
        >
          <Merge size={11} />
          {preparing ? "Merging..." : "Merge & Prepare"}
        </button>
        {prepareResult && prepareResult.status === "completed" && prepareResult.rows && prepareResult.rows > 0 && (
          <div className="bg-bg-main border border-border rounded p-3 flex flex-col gap-1.5 text-[10px]">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <span className="text-text-secondary">Rows</span>
              <span className="text-text-primary font-mono">{prepareResult.rows?.toLocaleString()}</span>
              <span className="text-text-secondary">Time range</span>
              <span className="text-text-primary font-mono text-[9px]">
                {prepareResult.time_range_start} to {prepareResult.time_range_end}
              </span>
              <span className="text-text-secondary">DEX price range</span>
              <span className="text-text-primary font-mono">{prepareResult.dex_price_range}</span>
              <span className="text-text-secondary">CEX price range</span>
              <span className="text-text-primary font-mono">{prepareResult.cex_price_range}</span>
              <span className="text-text-secondary">Avg spread</span>
              <span className="text-text-primary font-mono">{prepareResult.avg_spread_bps} bps</span>
              <span className="text-text-secondary">Max spread</span>
              <span className="text-text-primary font-mono">{prepareResult.max_spread_bps} bps</span>
              <span className="text-text-secondary">Data gaps</span>
              <span className="text-text-primary font-mono">{prepareResult.data_gaps_pct}%</span>
              <span className="text-text-secondary">Lag applied</span>
              <span className={`font-mono ${prepareResult.lag_applied ? "text-accent-green" : "text-accent-amber"}`}>
                {prepareResult.lag_applied ? "Yes" : "No"}
              </span>
            </div>
          </div>
        )}
        {prepareResult && prepareResult.status === "error" && (
          <div className="text-[10px] text-accent-red border border-accent-red/30 rounded px-2 py-1.5 bg-accent-red/5">
            {prepareResult.error}
          </div>
        )}
      </div>

      {/* Preview Modal */}
      <Modal
        open={!!previewFile}
        onClose={() => { setPreviewFile(null); setPreviewData(null); }}
        title={`Preview: ${previewFile ?? ""}`}
      >
        {previewLoading ? (
          <div className="py-8 text-center text-xs text-text-secondary">Loading…</div>
        ) : previewData ? (
          <div className="overflow-x-auto">
            <p className="text-[10px] text-text-secondary mb-2">
              Showing first {previewData.rows.length} rows · {previewData.columns.length} columns
            </p>
            <DataTable
              columns={previewColumns}
              data={previewData.rows}
            />
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-accent-red">
            Failed to load preview
          </div>
        )}
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Confirm Delete"
      >
        <div className="flex flex-col gap-4">
          <p className="text-sm text-text-primary">
            Delete <span className="font-mono text-accent-red">{deleteTarget}</span>? This cannot be undone.
          </p>
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setDeleteTarget(null)}
              className="px-3 py-1.5 text-xs bg-bg-main border border-border rounded hover:bg-bg-active transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={confirmDelete}
              disabled={deleting}
              className="px-3 py-1.5 text-xs bg-accent-red/20 border border-accent-red/50 text-accent-red rounded hover:bg-accent-red/30 disabled:opacity-40 transition-colors"
            >
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
