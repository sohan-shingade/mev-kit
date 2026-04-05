import { useEffect, useState, useCallback, useRef } from "react";
import { get, post, del } from "../api/client";
import type { DataFile } from "../api/types";
import Modal from "../components/common/Modal";
import DataTable from "../components/common/DataTable";
import { toast } from "../components/common/Toast";
import { RefreshCw, Trash2, Eye, Download } from "lucide-react";

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

// --- Market presets with venue-specific identifiers ---

interface MarketPreset {
  label: string;
  binance_symbol: string;
  birdeye_base: string;
  birdeye_quote: string;
  helius_pool: string;
}

const MARKET_PRESETS: MarketPreset[] = [
  {
    label: "SOL/USDC",
    binance_symbol: "SOLUSDT",
    birdeye_base: "So11111111111111111111111111111111111111112",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
  },
  {
    label: "SOL/USDT",
    binance_symbol: "SOLUSDT",
    birdeye_base: "So11111111111111111111111111111111111111112",
    birdeye_quote: "Es9vMFrzaCERmKfreVDyFe3GHMC3dYTzJ3tEX2s8VdDg",
    helius_pool: "7XawhbbxtsRcQA8KTkHT9f9nc6d69UwqCDh6U5EEbEmX",
  },
  {
    label: "WIF/USDC",
    binance_symbol: "WIFUSDT",
    birdeye_base: "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "",
  },
  {
    label: "JUP/USDC",
    binance_symbol: "JUPUSDT",
    birdeye_base: "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "",
  },
  {
    label: "BONK/USDC",
    binance_symbol: "BONKUSDT",
    birdeye_base: "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "",
  },
  {
    label: "RAY/USDC",
    binance_symbol: "RAYUSDT",
    birdeye_base: "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "6UmmUiYoBjSrhakAobJw8BvkmJtDVxaeBtbt7rxWo1mg",
  },
  {
    label: "JTO/USDC",
    binance_symbol: "JTOUSDT",
    birdeye_base: "jtojtomepa8beP8AuQc6eXt5FriJwfFwwn2LwDeFkt",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "",
  },
  {
    label: "PYTH/USDC",
    binance_symbol: "PYTHUSDT",
    birdeye_base: "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    birdeye_quote: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    helius_pool: "",
  },
  {
    label: "mSOL/SOL",
    binance_symbol: "",
    birdeye_base: "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    birdeye_quote: "So11111111111111111111111111111111111111112",
    helius_pool: "EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U",
  },
];

const RESOLUTION_OPTIONS = [
  { value: "1s", label: "1 second", binanceOnly: true },
  { value: "1m", label: "1 minute", binanceOnly: false },
  { value: "5m", label: "5 minutes", binanceOnly: false },
  { value: "15m", label: "15 minutes", binanceOnly: false },
  { value: "1h", label: "1 hour", binanceOnly: false },
];

const DURATION_OPTIONS = [
  { value: 1, label: "1 day" },
  { value: 3, label: "3 days" },
  { value: 7, label: "7 days" },
  { value: 14, label: "14 days" },
  { value: 30, label: "30 days" },
];

type VenueName = "binance" | "birdeye" | "helius";

interface MarketFetchJob {
  status: "running" | "completed" | "error";
  progress: number;
  total?: number;
  steps?: Record<string, string | number>;
  files?: Record<string, string>;
  merged_file?: string;
  merge_stats?: Record<string, unknown>;
  error?: string;
}

interface FetchJob {
  status: "running" | "completed" | "error";
  progress: number;
  total?: number;
  file?: string;
  rows?: number;
  error?: string;
  steps?: Record<string, string | number>;
  files?: Record<string, string>;
  merged_file?: string;
  merge_stats?: Record<string, unknown>;
}

export default function Data() {
  const [files, setFiles] = useState<DataFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Unified form state
  const [selectedMarket, setSelectedMarket] = useState<MarketPreset>(MARKET_PRESETS[0]);
  const [selectedVenues, setSelectedVenues] = useState<Set<VenueName>>(new Set(["binance", "birdeye"]));
  const [resolution, setResolution] = useState("1m");
  const [duration, setDuration] = useState(7);
  const [autoMerge, setAutoMerge] = useState(true);
  const [applyLag, setApplyLag] = useState(true);
  const [useBinanceUs, setUseBinanceUs] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Job tracking
  const [fetchJobs, setFetchJobs] = useState<Record<string, FetchJob>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // When market changes, update venue availability
  useEffect(() => {
    setSelectedVenues((prev) => {
      const next = new Set(prev);
      if (!selectedMarket.binance_symbol) next.delete("binance");
      if (!selectedMarket.birdeye_base) next.delete("birdeye");
      if (!selectedMarket.helius_pool) next.delete("helius");
      // Ensure at least one venue is selected
      if (next.size === 0) {
        if (selectedMarket.birdeye_base) next.add("birdeye");
        else if (selectedMarket.binance_symbol) next.add("binance");
      }
      return next;
    });
  }, [selectedMarket]);

  function toggleVenue(venue: VenueName) {
    setSelectedVenues((prev) => {
      const next = new Set(prev);
      if (next.has(venue)) {
        next.delete(venue);
      } else {
        next.add(venue);
      }
      return next;
    });
  }

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

  async function handleFetchMarket() {
    if (selectedVenues.size === 0) {
      toast("Select at least one venue", "warning");
      return;
    }
    setFetching(true);
    setActiveJobId(null);
    try {
      const result = await post<{ status: string; job_id?: string; error?: string }>(
        "/api/data/fetch/market",
        {
          market: { ...selectedMarket, use_binance_us: useBinanceUs },
          venues: Array.from(selectedVenues),
          interval: resolution,
          days: duration,
          auto_merge: autoMerge,
          lag: applyLag,
        }
      );
      if (result.status === "error") {
        toast(result.error ?? "Fetch failed", "error");
      } else {
        toast("Market data fetch started", "success");
        if (result.job_id) setActiveJobId(result.job_id);
        fetchJobStatus();
        if (!pollRef.current) {
          pollRef.current = setInterval(fetchJobStatus, 2000);
        }
      }
    } catch {
      toast("Failed to start market fetch", "error");
    } finally {
      setFetching(false);
    }
  }

  const venueCount = selectedVenues.size;
  const showMergeOptions = venueCount >= 2;
  const isHeliusSelected = selectedVenues.has("helius");

  // Get the active market job for progress display
  const activeJob: MarketFetchJob | null = activeJobId ? (fetchJobs[activeJobId] as MarketFetchJob | undefined) ?? null : null;

  // Also show sub-jobs for active market fetch
  const activeSubJobs: Record<string, FetchJob> = {};
  if (activeJobId) {
    for (const [id, job] of Object.entries(fetchJobs)) {
      if (id.startsWith(activeJobId + "_")) {
        activeSubJobs[id] = job;
      }
    }
  }

  const previewColumns = previewData
    ? previewData.columns.map((c) => ({ key: c, label: c }))
    : [];

  const inputCls =
    "bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono";

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
          <div className="py-8 text-center text-xs text-text-secondary">Loading...</div>
        ) : files.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            No data files found. Use the fetch form below to download market data.
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

      {/* Unified Fetch Market Data Form */}
      <div className="bg-bg-panel border border-border rounded p-4 flex flex-col gap-4">
        <h2 className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
          Fetch Market Data
        </h2>

        {/* Market selection */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-text-secondary">Market</label>
          <select
            value={selectedMarket.label}
            onChange={(e) => {
              const preset = MARKET_PRESETS.find((p) => p.label === e.target.value);
              if (preset) setSelectedMarket(preset);
            }}
            className={inputCls}
          >
            {MARKET_PRESETS.map((p) => (
              <option key={p.label} value={p.label}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {/* Venues */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] text-text-secondary">Venues</label>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {/* Binance */}
            <label
              className={`flex items-center gap-1.5 text-xs cursor-pointer select-none ${
                !selectedMarket.binance_symbol ? "opacity-40 cursor-not-allowed" : ""
              }`}
              title={
                !selectedMarket.binance_symbol
                  ? `${selectedMarket.label} is not listed on Binance`
                  : "Binance CEX historical OHLCV"
              }
            >
              <input
                type="checkbox"
                checked={selectedVenues.has("binance")}
                disabled={!selectedMarket.binance_symbol}
                onChange={() => toggleVenue("binance")}
                className="accent-accent-amber"
              />
              <span className="text-text-primary">Binance</span>
              <span className="text-[10px] text-text-secondary">(CEX)</span>
            </label>
            {selectedVenues.has("binance") && (
              <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none ml-1">
                <input
                  type="checkbox"
                  checked={useBinanceUs}
                  onChange={(e) => setUseBinanceUs(e.target.checked)}
                  className="accent-accent-indigo"
                />
                <span className="text-text-secondary">US endpoint</span>
              </label>
            )}

            {/* Birdeye */}
            <label
              className={`flex items-center gap-1.5 text-xs cursor-pointer select-none ${
                !selectedMarket.birdeye_base ? "opacity-40 cursor-not-allowed" : ""
              }`}
              title={
                !selectedMarket.birdeye_base
                  ? `${selectedMarket.label} not available on Birdeye`
                  : "Birdeye DEX aggregated OHLCV"
              }
            >
              <input
                type="checkbox"
                checked={selectedVenues.has("birdeye")}
                disabled={!selectedMarket.birdeye_base}
                onChange={() => toggleVenue("birdeye")}
                className="accent-accent-green"
              />
              <span className="text-text-primary">Birdeye</span>
              <span className="text-[10px] text-text-secondary">(DEX)</span>
            </label>

            {/* Helius */}
            <label
              className={`flex items-center gap-1.5 text-xs cursor-pointer select-none ${
                !selectedMarket.helius_pool ? "opacity-40 cursor-not-allowed" : ""
              }`}
              title={
                !selectedMarket.helius_pool
                  ? `No pool address configured for ${selectedMarket.label}`
                  : "Helius on-chain live poll (real-time, short duration only)"
              }
            >
              <input
                type="checkbox"
                checked={selectedVenues.has("helius")}
                disabled={!selectedMarket.helius_pool}
                onChange={() => toggleVenue("helius")}
                className="accent-accent-indigo"
              />
              <span className="text-text-primary">Helius</span>
              <span className="text-[10px] text-text-secondary">(live poll)</span>
            </label>
          </div>
        </div>

        {/* Resolution + Duration */}
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-text-secondary">Resolution</label>
            <select
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              className={inputCls}
            >
              {RESOLUTION_OPTIONS.map((r) => {
                // 1s only available for Binance
                const disabled = r.binanceOnly && !selectedVenues.has("binance");
                return (
                  <option key={r.value} value={r.value} disabled={disabled}>
                    {r.label}
                    {r.binanceOnly ? " (Binance only)" : ""}
                  </option>
                );
              })}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-text-secondary">
              Duration
              {isHeliusSelected && (
                <span className="text-accent-amber ml-1">(Helius capped at 1 hr)</span>
              )}
            </label>
            <select
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              className={inputCls}
            >
              {DURATION_OPTIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Merge + Lag options */}
        {showMergeOptions && (
          <div className="flex flex-col gap-2 border border-border/50 rounded p-3 bg-bg-main/30">
            <label className="flex items-center gap-1.5 text-xs text-text-primary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={autoMerge}
                onChange={(e) => setAutoMerge(e.target.checked)}
                className="accent-accent-indigo"
              />
              Auto-merge & align
              <span className="text-[10px] text-text-secondary">(recommended)</span>
            </label>
            {autoMerge && (
              <label className="flex items-center gap-1.5 text-xs text-text-primary cursor-pointer select-none ml-5">
                <input
                  type="checkbox"
                  checked={applyLag}
                  onChange={(e) => setApplyLag(e.target.checked)}
                  className="accent-accent-indigo"
                />
                Apply lag
                <span className="text-[10px] text-text-secondary">(prevent lookahead bias)</span>
              </label>
            )}
          </div>
        )}

        {/* Helius note */}
        {isHeliusSelected && (
          <div className="text-[10px] text-accent-amber border border-accent-amber/30 rounded px-2 py-1.5 bg-accent-amber/5">
            Helius is a live poll -- it fetches current on-chain state in real-time. Duration is
            capped at 1 hour regardless of the setting above. For historical data, use Binance +
            Birdeye.
          </div>
        )}

        {/* Fetch button */}
        <button
          onClick={handleFetchMarket}
          disabled={fetching || selectedVenues.size === 0}
          className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
        >
          {fetching ? "Starting..." : "Fetch & Prepare"}
        </button>

        {/* Progress section */}
        {activeJob && (
          <div className="flex flex-col gap-2 border border-border/50 rounded p-3 bg-bg-main/30">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
                Progress
              </span>
              <span
                className={`text-[10px] font-semibold ${
                  activeJob.status === "completed"
                    ? "text-accent-green"
                    : activeJob.status === "error"
                    ? "text-accent-red"
                    : "text-accent-amber"
                }`}
              >
                {activeJob.status === "completed"
                  ? "Complete"
                  : activeJob.status === "error"
                  ? activeJob.error ?? "Error"
                  : `${activeJob.progress ?? 0} / ${activeJob.total ?? "?"}`}
              </span>
            </div>

            <div className="flex flex-col gap-1.5">
              {/* Binance step */}
              {activeJob.steps && "binance" in activeJob.steps && (
                <StepRow
                  label={`Binance ${selectedMarket.binance_symbol}`}
                  status={String(activeJob.steps.binance)}
                  rows={activeJob.steps.binance_rows as number | undefined}
                  subJob={activeSubJobs[`${activeJobId}_binance`]}
                />
              )}

              {/* Birdeye step */}
              {activeJob.steps && "birdeye" in activeJob.steps && (
                <StepRow
                  label={`Birdeye ${selectedMarket.label}`}
                  status={String(activeJob.steps.birdeye)}
                  rows={activeJob.steps.birdeye_rows as number | undefined}
                  subJob={activeSubJobs[`${activeJobId}_birdeye`]}
                />
              )}

              {/* Helius step */}
              {activeJob.steps && "helius" in activeJob.steps && (
                <StepRow
                  label={`Helius ${selectedMarket.label}`}
                  status={String(activeJob.steps.helius)}
                  rows={activeJob.steps.helius_rows as number | undefined}
                  subJob={activeSubJobs[`${activeJobId}_helius`]}
                />
              )}

              {/* Merge step */}
              {activeJob.steps && "merge" in activeJob.steps && (
                <StepRow
                  label="Merge & align"
                  status={String(activeJob.steps.merge)}
                />
              )}
            </div>

            {/* Merge stats */}
            {activeJob.status === "completed" && activeJob.merge_stats && (
              <div className="mt-1 bg-bg-main border border-border rounded p-3 flex flex-col gap-1.5 text-[10px]">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                  {activeJob.merge_stats.rows != null && (
                    <>
                      <span className="text-text-secondary">Rows</span>
                      <span className="text-text-primary font-mono">
                        {Number(activeJob.merge_stats.rows).toLocaleString()}
                      </span>
                    </>
                  )}
                  {activeJob.merge_stats.time_range_start != null && (
                    <>
                      <span className="text-text-secondary">Time range</span>
                      <span className="text-text-primary font-mono text-[9px]">
                        {String(activeJob.merge_stats.time_range_start)} to{" "}
                        {String(activeJob.merge_stats.time_range_end)}
                      </span>
                    </>
                  )}
                  {activeJob.merge_stats.avg_spread_bps != null && (
                    <>
                      <span className="text-text-secondary">Avg spread</span>
                      <span className="text-text-primary font-mono">
                        {String(activeJob.merge_stats.avg_spread_bps)} bps
                      </span>
                    </>
                  )}
                  {activeJob.merge_stats.max_spread_bps != null && (
                    <>
                      <span className="text-text-secondary">Max spread</span>
                      <span className="text-text-primary font-mono">
                        {String(activeJob.merge_stats.max_spread_bps)} bps
                      </span>
                    </>
                  )}
                  {activeJob.merge_stats.data_gaps_pct != null && (
                    <>
                      <span className="text-text-secondary">Data gaps</span>
                      <span className="text-text-primary font-mono">
                        {String(activeJob.merge_stats.data_gaps_pct)}%
                      </span>
                    </>
                  )}
                  {activeJob.merge_stats.lag_applied != null && (
                    <>
                      <span className="text-text-secondary">Lag applied</span>
                      <span
                        className={`font-mono ${
                          activeJob.merge_stats.lag_applied
                            ? "text-accent-green"
                            : "text-accent-amber"
                        }`}
                      >
                        {activeJob.merge_stats.lag_applied ? "Yes" : "No"}
                      </span>
                    </>
                  )}
                  {activeJob.merged_file && (
                    <>
                      <span className="text-text-secondary">Output</span>
                      <span className="text-text-primary font-mono text-[9px]">
                        {activeJob.merged_file}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Preview Modal */}
      <Modal
        open={!!previewFile}
        onClose={() => {
          setPreviewFile(null);
          setPreviewData(null);
        }}
        title={`Preview: ${previewFile ?? ""}`}
      >
        {previewLoading ? (
          <div className="py-8 text-center text-xs text-text-secondary">Loading...</div>
        ) : previewData ? (
          <div className="overflow-x-auto">
            <p className="text-[10px] text-text-secondary mb-2">
              Showing first {previewData.rows.length} rows / {previewData.columns.length} columns
            </p>
            <DataTable columns={previewColumns} data={previewData.rows} />
          </div>
        ) : (
          <div className="py-4 text-center text-xs text-accent-red">Failed to load preview</div>
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
            Delete <span className="font-mono text-accent-red">{deleteTarget}</span>? This cannot be
            undone.
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
              {deleting ? "Deleting..." : "Delete"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/** Step row in the progress section. */
function StepRow({
  label,
  status,
  rows,
  subJob,
}: {
  label: string;
  status: string;
  rows?: number;
  subJob?: FetchJob;
}) {
  const isCompleted = status === "completed";
  const isRunning = status === "running";
  const isError = status.startsWith("error");
  // Use sub-job progress if available and still running
  const progressText =
    isRunning && subJob
      ? `${subJob.progress?.toLocaleString() ?? 0}${subJob.total ? ` / ${subJob.total.toLocaleString()}` : ""}`
      : isCompleted && rows
      ? `${rows.toLocaleString()} rows`
      : isError
      ? status.replace("error: ", "")
      : "";

  const icon = isCompleted
    ? "\u2713"
    : isRunning
    ? "\u21BB"
    : isError
    ? "\u2717"
    : "\u25CB";

  const iconColor = isCompleted
    ? "text-accent-green"
    : isRunning
    ? "text-accent-amber"
    : isError
    ? "text-accent-red"
    : "text-text-secondary";

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`font-mono text-sm w-4 text-center ${iconColor}`}>{icon}</span>
      <span className="text-text-primary">{label}</span>
      {progressText && (
        <span className={`ml-auto font-mono text-[10px] ${iconColor}`}>{progressText}</span>
      )}
    </div>
  );
}
