import { useEffect, useState } from "react";
import { get, put } from "../api/client";
import type { ConfigProfile } from "../api/types";
import { toast } from "../components/common/Toast";
import { ChevronDown, ChevronRight, Save, FolderOpen } from "lucide-react";

interface EnvStatus {
  HELIUS_API_KEY: boolean;
  HELIUS_RPC_URL: boolean;
  SOLANA_RPC_URL: boolean;
  BINANCE_WS_URL: boolean;
  JITO_BLOCK_ENGINE_URL: boolean;
  WALLET_KEYPAIR_PATH: boolean;
}

function AccordionSection({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-bg-panel text-xs font-semibold uppercase tracking-wider text-text-secondary hover:bg-bg-active transition-colors"
      >
        {title}
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="bg-bg-main p-3 flex flex-col gap-3">{children}</div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-text-secondary uppercase tracking-wider">
        {label}
      </label>
      {children}
    </div>
  );
}

function inputCls() {
  return "bg-bg-panel border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-indigo font-mono";
}

const ADAPTER_OPTIONS = [
  "helius_ws",
  "binance_ws",
  "jupiter",
  "parquet_replay",
  "geyser",
  "yellowstone_grpc",
];

const SINK_TYPES = ["paper_trade", "backtest", "jito_bundle", "direct_tpu"];
const SIM_TYPES = ["rpc", "local_validator", "forked_state"];

export default function Config() {
  const [profiles, setProfiles] = useState<string[]>([]);
  const [selectedProfile, setSelectedProfile] = useState("free");
  const [config, setConfig] = useState<ConfigProfile>({
    pipeline: {},
    strategy: {},
    simulator: {},
    sink: {},
    risk: {},
    ingest: {},
  });
  const [envStatus, setEnvStatus] = useState<EnvStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveAsName, setSaveAsName] = useState("");
  const [showSaveAs, setShowSaveAs] = useState(false);

  useEffect(() => {
    get<string[]>("/api/config/profiles")
      .then(setProfiles)
      .catch(() => setProfiles(["free", "pro"]));
  }, []);

  useEffect(() => {
    get<ConfigProfile>(`/api/config?profile=${selectedProfile}`)
      .then(setConfig)
      .catch(() => {});
    get<EnvStatus>("/api/config/env")
      .then(setEnvStatus)
      .catch(() => {});
  }, [selectedProfile]);

  function setStrategy(key: string, value: unknown) {
    setConfig((c) => ({ ...c, strategy: { ...c.strategy, [key]: value } }));
  }
  function setSimulator(key: string, value: unknown) {
    setConfig((c) => ({ ...c, simulator: { ...c.simulator, [key]: value } }));
  }
  function setSink(key: string, value: unknown) {
    setConfig((c) => ({ ...c, sink: { ...c.sink, [key]: value } }));
  }
  function setRisk(key: string, value: unknown) {
    setConfig((c) => ({ ...c, risk: { ...c.risk, [key]: value } }));
  }

  function toggleAdapter(a: string) {
    const current = (config.ingest?.adapters as string[] | undefined) ?? [];
    const next = current.includes(a)
      ? current.filter((x) => x !== a)
      : [...current, a];
    setConfig((c) => ({ ...c, ingest: { ...c.ingest, adapters: next } }));
  }

  async function handleSave(profile = selectedProfile) {
    setSaving(true);
    try {
      await put(`/api/config?profile=${profile}`, config);
      toast(`Saved profile "${profile}"`, "success");
      if (!profiles.includes(profile)) {
        setProfiles((p) => [...p, profile]);
      }
      setSelectedProfile(profile);
      setShowSaveAs(false);
      setSaveAsName("");
    } catch {
      toast("Failed to save config", "error");
    } finally {
      setSaving(false);
    }
  }

  const strategy = config.strategy ?? {};
  const sim = config.simulator ?? {};
  const sink = config.sink ?? {};
  const risk = config.risk ?? {};
  const adapters = (config.ingest?.adapters as string[] | undefined) ?? [];

  return (
    <div className="p-4 flex flex-col gap-4 max-w-2xl">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Configuration
        </h1>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <FolderOpen size={12} className="text-text-secondary" />
            <select
              value={selectedProfile}
              onChange={(e) => setSelectedProfile(e.target.value)}
              className="bg-bg-panel border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-indigo"
            >
              {profiles.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => handleSave()}
            disabled={saving}
            className="flex items-center gap-1.5 px-3 py-1 text-xs bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
          >
            <Save size={11} />
            {saving ? "Saving…" : "Save"}
          </button>
          <button
            onClick={() => setShowSaveAs((v) => !v)}
            className="px-3 py-1 text-xs bg-bg-panel border border-border rounded hover:bg-bg-active transition-colors"
          >
            Save As
          </button>
        </div>
      </div>

      {showSaveAs && (
        <div className="flex items-center gap-2 bg-bg-panel border border-border rounded p-2">
          <input
            value={saveAsName}
            onChange={(e) => setSaveAsName(e.target.value)}
            placeholder="profile name"
            className="bg-bg-main border border-border rounded px-2 py-1 text-xs flex-1 focus:outline-none focus:border-accent-indigo"
          />
          <button
            onClick={() => saveAsName.trim() && handleSave(saveAsName.trim())}
            disabled={!saveAsName.trim() || saving}
            className="px-3 py-1 text-xs bg-accent-indigo/20 border border-accent-indigo/50 text-accent-indigo rounded hover:bg-accent-indigo/30 disabled:opacity-40 transition-colors"
          >
            Save
          </button>
          <button
            onClick={() => setShowSaveAs(false)}
            className="px-2 py-1 text-xs text-text-secondary hover:text-text-primary"
          >
            Cancel
          </button>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <AccordionSection title="Strategy" defaultOpen>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Min Spread (bps)">
              <input
                type="number"
                value={(strategy.min_spread_bps as number) ?? 20}
                onChange={(e) => setStrategy("min_spread_bps", Number(e.target.value))}
                className={inputCls()}
              />
            </Field>
            <Field label="Fee (bps)">
              <input
                type="number"
                value={(strategy.fee_bps as number) ?? 5}
                onChange={(e) => setStrategy("fee_bps", Number(e.target.value))}
                className={inputCls()}
              />
            </Field>
            <Field label="Pair">
              <input
                type="text"
                value={(strategy.pair as string) ?? "SOL/USDC"}
                onChange={(e) => setStrategy("pair", e.target.value)}
                className={inputCls()}
              />
            </Field>
            <Field label="Position Size (SOL)">
              <input
                type="number"
                step="0.01"
                value={(strategy.position_size_sol as number) ?? 0.1}
                onChange={(e) =>
                  setStrategy("position_size_sol", Number(e.target.value))
                }
                className={inputCls()}
              />
            </Field>
          </div>
        </AccordionSection>

        <AccordionSection title="Adapters">
          <div className="flex flex-wrap gap-2">
            {ADAPTER_OPTIONS.map((a) => (
              <label
                key={a}
                className="flex items-center gap-1.5 cursor-pointer text-xs"
              >
                <input
                  type="checkbox"
                  checked={adapters.includes(a)}
                  onChange={() => toggleAdapter(a)}
                  className="accent-accent-indigo"
                />
                <span className="font-mono text-text-primary">{a}</span>
              </label>
            ))}
          </div>
        </AccordionSection>

        <AccordionSection title="Simulator">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <select
                value={(sim.type as string) ?? "rpc"}
                onChange={(e) => setSimulator("type", e.target.value)}
                className={inputCls()}
              >
                {SIM_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Simulate Before Execute">
              <label className="flex items-center gap-2 mt-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={(sim.simulate_before_execute as boolean) ?? true}
                  onChange={(e) =>
                    setSimulator("simulate_before_execute", e.target.checked)
                  }
                  className="accent-accent-indigo"
                />
                <span className="text-xs text-text-secondary">Enabled</span>
              </label>
            </Field>
          </div>
        </AccordionSection>

        <AccordionSection title="Sink">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <select
                value={(sink.type as string) ?? "paper_trade"}
                onChange={(e) => setSink("type", e.target.value)}
                className={inputCls()}
              >
                {SINK_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="DB Path">
              <input
                type="text"
                value={(sink.db_path as string) ?? "./data/results.db"}
                onChange={(e) => setSink("db_path", e.target.value)}
                className={inputCls()}
              />
            </Field>
          </div>
        </AccordionSection>

        <AccordionSection title="Risk">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max Daily Loss (SOL)">
              <input
                type="number"
                step="0.01"
                value={(risk.max_daily_loss_sol as number) ?? 0.5}
                onChange={(e) => setRisk("max_daily_loss_sol", Number(e.target.value))}
                className={inputCls()}
              />
            </Field>
            <Field label="Max Consecutive Misses">
              <input
                type="number"
                value={(risk.max_consecutive_misses as number) ?? 10}
                onChange={(e) =>
                  setRisk("max_consecutive_misses", Number(e.target.value))
                }
                className={inputCls()}
              />
            </Field>
            <Field label="Circuit Breaker">
              <label className="flex items-center gap-2 mt-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={(risk.circuit_breaker_enabled as boolean) ?? true}
                  onChange={(e) =>
                    setRisk("circuit_breaker_enabled", e.target.checked)
                  }
                  className="accent-accent-indigo"
                />
                <span className="text-xs text-text-secondary">Enabled</span>
              </label>
            </Field>
          </div>
        </AccordionSection>

        <AccordionSection title="API Keys">
          {envStatus ? (
            <div className="flex flex-col gap-2">
              {(Object.entries(envStatus) as [string, boolean][]).map(
                ([key, set]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between py-1 border-b border-border/40 last:border-0"
                  >
                    <span className="text-xs font-mono text-text-primary">{key}</span>
                    <span
                      className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                        set
                          ? "bg-accent-green/10 text-accent-green"
                          : "bg-accent-red/10 text-accent-red"
                      }`}
                    >
                      {set ? "SET" : "MISSING"}
                    </span>
                  </div>
                )
              )}
              <p className="text-[10px] text-text-secondary mt-1">
                Set via environment variables — values are never shown in the UI.
              </p>
            </div>
          ) : (
            <span className="text-xs text-text-secondary italic">Loading…</span>
          )}
        </AccordionSection>
      </div>
    </div>
  );
}
