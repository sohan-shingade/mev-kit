import { useEffect, useState, useRef } from "react";
import Editor from "@monaco-editor/react";
import { get, put, post } from "../api/client";
import { toast } from "../components/common/Toast";
import {
  FileCode2,
  Save,
  Plus,
  CheckCircle2,
  AlertCircle,
  Sparkles,
} from "lucide-react";

interface StrategyFile {
  name: string;
  path: string;
  type: "user" | "example";
  size: number;
}

interface ValidationResult {
  valid: boolean;
  error?: string;
  line?: number;
  col?: number;
  has_detector_class?: boolean;
  has_process_method?: boolean;
  warnings?: string[];
}

const DATA_SOURCE_INFO: Record<string, { label: string; description: string; free: boolean }> = {
  HELIUS_WS: { label: "Helius WebSocket", description: "Raydium pool state changes via accountSubscribe", free: true },
  BINANCE_WS: { label: "Binance WebSocket", description: "Real-time CEX trade data (no API key)", free: true },
  YELLOWSTONE_GRPC: { label: "Yellowstone gRPC", description: "High-performance Solana streaming", free: false },
  GEYSER: { label: "Geyser Plugin", description: "Direct validator account notifications", free: false },
  JUPITER_API: { label: "Jupiter API", description: "Swap routing and price quotes", free: true },
  PARQUET_REPLAY: { label: "Parquet Replay", description: "Historical data replay for backtesting", free: true },
};

export default function StrategyEditor() {
  const [files, setFiles] = useState<StrategyFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [originalCode, setOriginalCode] = useState("");
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const editorRef = useRef<unknown>(null);

  // Load file list
  useEffect(() => {
    get<StrategyFile[]>("/api/strategies/files").then(setFiles).catch(() => {});
  }, []);

  // Load file content
  useEffect(() => {
    if (!selectedPath) return;
    get<{ content: string; error?: string }>(`/api/strategies/files/${selectedPath}`)
      .then((r) => {
        if (r.error) {
          toast(r.error, "error");
          return;
        }
        setCode(r.content);
        setOriginalCode(r.content);
        setValidation(null);
      })
      .catch(() => toast("Failed to load file", "error"));
  }, [selectedPath]);

  const hasChanges = code !== originalCode;
  const isExample = files.find((f) => f.path === selectedPath)?.type === "example";

  async function handleSave() {
    if (!selectedPath || isExample) return;
    setSaving(true);
    try {
      const res = await put<{ status?: string; error?: string }>(
        `/api/strategies/files/${selectedPath}`,
        { content: code }
      );
      if (res.error) {
        toast(res.error, "error");
      } else {
        toast("Strategy saved", "success");
        setOriginalCode(code);
        // Refresh file list
        const f = await get<StrategyFile[]>("/api/strategies/files");
        setFiles(f);
      }
    } catch {
      toast("Failed to save", "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleValidate() {
    setValidating(true);
    try {
      const result = await post<ValidationResult>("/api/strategies/validate", { content: code });
      setValidation(result);
      if (result.valid) {
        toast("Syntax valid", "success");
      } else {
        toast(result.error ?? "Validation failed", "error");
      }
    } catch {
      toast("Validation failed", "error");
    } finally {
      setValidating(false);
    }
  }

  async function handleNewStrategy() {
    try {
      const res = await get<{ content: string }>("/api/strategies/template");
      const name = prompt("Strategy filename (e.g. my_detector.py):");
      if (!name) return;
      const filename = name.endsWith(".py") ? name : `${name}.py`;
      setCode(res.content);
      setOriginalCode("");
      setSelectedPath(filename);
      // Save immediately to create the file
      await put(`/api/strategies/files/${filename}`, { content: res.content });
      const f = await get<StrategyFile[]>("/api/strategies/files");
      setFiles(f);
      toast(`Created ${filename}`, "success");
    } catch {
      toast("Failed to create strategy", "error");
    }
  }

  // Extract required_sources from code
  const sourcesMatch = code.match(/required_sources\s*=\s*\{([^}]+)\}/);
  const detectedSources = sourcesMatch
    ? sourcesMatch[1]
        .split(",")
        .map((s) => s.trim().replace("Source.", ""))
        .filter(Boolean)
    : [];

  const userFiles = files.filter((f) => f.type === "user");
  const exampleFiles = files.filter((f) => f.type === "example");

  return (
    <div className="flex h-full min-h-0">
      {/* ── File sidebar ── */}
      <div className="w-[200px] shrink-0 bg-bg-sidebar border-r border-border flex flex-col overflow-y-auto">
        <div className="px-3 py-3 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <FileCode2 size={13} className="text-accent-indigo" />
            <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
              Strategies
            </span>
          </div>
          <button
            onClick={handleNewStrategy}
            className="p-1 text-text-secondary hover:text-accent-green transition-colors"
            title="New Strategy"
          >
            <Plus size={14} />
          </button>
        </div>

        {/* User strategies */}
        {userFiles.length > 0 && (
          <div className="px-2 py-2">
            <div className="px-2 mb-1">
              <span className="text-[9px] text-text-secondary uppercase tracking-wider">
                Your Strategies
              </span>
            </div>
            {userFiles.map((f) => (
              <button
                key={f.path}
                onClick={() => setSelectedPath(f.path)}
                className={`w-full text-left flex items-center gap-1.5 px-2 py-1.5 rounded text-xs transition-colors ${
                  selectedPath === f.path
                    ? "bg-accent-indigo/20 text-accent-indigo"
                    : "text-text-secondary hover:bg-bg-active/50 hover:text-text-primary"
                }`}
              >
                <FileCode2 size={11} className="shrink-0" />
                <span className="truncate">{f.name}</span>
              </button>
            ))}
          </div>
        )}

        {/* Example strategies */}
        <div className="px-2 py-2 border-t border-border">
          <div className="px-2 mb-1">
            <span className="text-[9px] text-text-secondary uppercase tracking-wider">
              Examples
            </span>
          </div>
          {exampleFiles.map((f) => (
            <button
              key={f.path}
              onClick={() => setSelectedPath(f.path)}
              className={`w-full text-left flex items-center gap-1.5 px-2 py-1.5 rounded text-xs transition-colors ${
                selectedPath === f.path
                  ? "bg-accent-amber/20 text-accent-amber"
                  : "text-text-secondary hover:bg-bg-active/50 hover:text-text-primary"
              }`}
            >
              <Sparkles size={11} className="shrink-0" />
              <span className="truncate">{f.name.replace(".py", "")}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Editor area ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedPath ? (
          <>
            {/* Toolbar */}
            <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-bg-panel/30">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-text-primary">{selectedPath}</span>
                {isExample && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-accent-amber/20 text-accent-amber rounded">
                    READ ONLY
                  </span>
                )}
                {hasChanges && !isExample && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-accent-green/20 text-accent-green rounded">
                    MODIFIED
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleValidate}
                  disabled={validating}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors disabled:opacity-40"
                >
                  <CheckCircle2 size={11} />
                  {validating ? "Checking..." : "Validate"}
                </button>
                {!isExample && (
                  <button
                    onClick={handleSave}
                    disabled={saving || !hasChanges}
                    className="flex items-center gap-1 px-2 py-1 text-[10px] bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
                  >
                    <Save size={11} />
                    {saving ? "Saving..." : "Save"}
                  </button>
                )}
              </div>
            </div>

            {/* Monaco Editor */}
            <div className="flex-1 min-h-0">
              <Editor
                height="100%"
                language="python"
                theme="vs-dark"
                value={code}
                onChange={(v) => setCode(v ?? "")}
                onMount={(editor) => { editorRef.current = editor; }}
                options={{
                  fontSize: 13,
                  fontFamily: "'SF Mono', Monaco, 'Cascadia Code', monospace",
                  minimap: { enabled: false },
                  lineNumbers: "on",
                  renderLineHighlight: "line",
                  scrollBeyondLastLine: false,
                  padding: { top: 12 },
                  readOnly: isExample,
                  wordWrap: "on",
                }}
              />
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <FileCode2 size={32} className="mx-auto text-text-secondary mb-3" />
              <p className="text-sm text-text-secondary">Select a strategy or create a new one</p>
              <button
                onClick={handleNewStrategy}
                className="mt-3 flex items-center gap-1.5 mx-auto px-3 py-1.5 text-xs bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 transition-colors"
              >
                <Plus size={12} />
                New Strategy
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Right info panel ── */}
      {selectedPath && (
        <div className="w-[220px] shrink-0 bg-bg-sidebar border-l border-border overflow-y-auto">
          {/* Validation status */}
          <div className="px-3 py-3 border-b border-border">
            <div className="text-[9px] text-text-secondary uppercase tracking-wider mb-2">
              Validation
            </div>
            {validation === null ? (
              <p className="text-xs text-text-secondary italic">Click Validate to check syntax</p>
            ) : validation.valid ? (
              <div className="flex items-center gap-1.5 text-xs text-accent-green">
                <CheckCircle2 size={13} />
                <span>Valid Python</span>
              </div>
            ) : (
              <div className="flex items-start gap-1.5 text-xs text-accent-red">
                <AlertCircle size={13} className="shrink-0 mt-0.5" />
                <span>{validation.error}</span>
              </div>
            )}
            {validation?.warnings && validation.warnings.length > 0 && (
              <div className="mt-2 space-y-1">
                {validation.warnings.map((w, i) => (
                  <p key={i} className="text-[10px] text-accent-amber">{w}</p>
                ))}
              </div>
            )}
          </div>

          {/* Detected data sources */}
          <div className="px-3 py-3 border-b border-border">
            <div className="text-[9px] text-text-secondary uppercase tracking-wider mb-2">
              Required Data Sources
            </div>
            {detectedSources.length > 0 ? (
              <div className="space-y-2">
                {detectedSources.map((s) => {
                  const info = DATA_SOURCE_INFO[s];
                  return (
                    <div key={s} className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${info?.free ? "bg-accent-green" : "bg-accent-amber"}`} />
                        <span className="text-xs text-text-primary">{info?.label ?? s}</span>
                      </div>
                      {info && (
                        <p className="text-[10px] text-text-secondary ml-3">
                          {info.description}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-text-secondary italic">
                No required_sources declared
              </p>
            )}
          </div>

          {/* Quick reference */}
          <div className="px-3 py-3">
            <div className="text-[9px] text-text-secondary uppercase tracking-wider mb-2">
              Quick Reference
            </div>
            <div className="space-y-1.5 text-[10px]">
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">process(update)</span>
                <span className="ml-1">— core detection</span>
              </div>
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">sync_state()</span>
                <span className="ml-1">— init hook</span>
              </div>
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">before(update)</span>
                <span className="ml-1">— pre-process</span>
              </div>
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">filters()</span>
                <span className="ml-1">— validation</span>
              </div>
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">required_sources</span>
                <span className="ml-1">— data feeds</span>
              </div>
              <div className="text-text-secondary">
                <span className="text-accent-indigo font-mono">hyperparameters()</span>
                <span className="ml-1">— optimization</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
