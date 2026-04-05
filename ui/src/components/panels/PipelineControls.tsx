import { useEffect, useState } from "react";
import { post, get } from "../../api/client";
import { toast } from "../common/Toast";
import Modal from "../common/Modal";

interface Props {
  state: string;
  mode: string | null;
}

export default function PipelineControls({ state, mode }: Props) {
  const [selectedMode, setSelectedMode] = useState("paper");
  const [selectedProfile, setSelectedProfile] = useState("free");
  const [selectedStrategy, setSelectedStrategy] = useState("");
  const [profiles, setProfiles] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [showStopConfirm, setShowStopConfirm] = useState(false);

  // Fetch config profiles and strategy files on mount
  useEffect(() => {
    get<string[]>("/api/config/profiles")
      .then((data) => {
        setProfiles(data);
        if (data.length > 0 && !data.includes(selectedProfile)) {
          setSelectedProfile(data[0]);
        }
      })
      .catch(() => {
        // Fall back to hardcoded defaults
        setProfiles(["free", "pro"]);
      });

    get<{ name: string; path: string; type: string }[]>("/api/strategies/files")
      .then((data) => {
        const names = data.map((s) => s.path.replace(".py", "").replace("examples/", ""));
        setStrategies(names);
        if (names.length > 0) setSelectedStrategy(names[0]);
      })
      .catch(() => {
        setStrategies(["cex_dex_arb"]);
        setSelectedStrategy("cex_dex_arb");
      });
  }, []);

  const doStart = async () => {
    try {
      await post("/api/pipeline/start", {
        mode: selectedMode,
        config_profile: selectedProfile,
        strategy: selectedStrategy,
        config: {},
      });
    } catch {
      toast("Failed to start pipeline", "error");
    }
  };

  const handleStart = () => {
    if (selectedMode === "live") {
      setShowLiveConfirm(true);
    } else {
      void doStart();
    }
  };

  const doStop = async () => {
    try {
      await post("/api/pipeline/stop", {});
    } catch {
      toast("Failed to stop pipeline", "error");
    }
  };

  const handleStop = () => {
    if (mode === "live") {
      setShowStopConfirm(true);
    } else {
      void doStop();
    }
  };

  if (state === "running") {
    return (
      <>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStop}
            className="px-3 py-1 bg-accent-red/20 text-accent-red text-xs rounded hover:bg-accent-red/30 transition-colors"
          >
            Stop
          </button>
        </div>

        {/* Stop confirmation modal (live mode) */}
        <Modal
          open={showStopConfirm}
          onClose={() => setShowStopConfirm(false)}
          title="Stop Live Pipeline"
        >
          <p className="text-sm text-text-primary mb-4">
            Stop the live pipeline? Any in-flight transactions will complete.
          </p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowStopConfirm(false)}
              className="px-3 py-1.5 text-xs border border-border rounded hover:bg-bg-active transition-colors text-text-secondary"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                setShowStopConfirm(false);
                void doStop();
              }}
              className="px-3 py-1.5 text-xs bg-accent-red/20 text-accent-red rounded hover:bg-accent-red/30 transition-colors"
            >
              Stop Pipeline
            </button>
          </div>
        </Modal>
      </>
    );
  }

  return (
    <>
      <div className="flex items-center gap-2">
        {/* Config profile dropdown */}
        <select
          value={selectedProfile}
          onChange={(e) => setSelectedProfile(e.target.value)}
          className="bg-bg-panel border border-border text-xs rounded px-2 py-1 text-text-primary"
          title="Config profile"
        >
          {profiles.length > 0 ? (
            profiles.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))
          ) : (
            <>
              <option value="free">free</option>
              <option value="pro">pro</option>
            </>
          )}
        </select>

        {/* Strategy dropdown */}
        <select
          value={selectedStrategy}
          onChange={(e) => setSelectedStrategy(e.target.value)}
          className="bg-bg-panel border border-border text-xs rounded px-2 py-1 text-text-primary"
          title="Strategy"
        >
          {strategies.length > 0 ? (
            strategies.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))
          ) : (
            <option value="cex_dex_arb">cex_dex_arb</option>
          )}
        </select>

        {/* Mode dropdown */}
        <select
          value={selectedMode}
          onChange={(e) => setSelectedMode(e.target.value)}
          className="bg-bg-panel border border-border text-xs rounded px-2 py-1 text-text-primary"
        >
          <option value="paper">Paper</option>
          <option value="live">Live</option>
        </select>

        <button
          onClick={handleStart}
          className="px-3 py-1 bg-accent-green/20 text-accent-green text-xs rounded hover:bg-accent-green/30 transition-colors"
        >
          Start
        </button>
      </div>

      {/* Live mode confirmation modal */}
      <Modal
        open={showLiveConfirm}
        onClose={() => setShowLiveConfirm(false)}
        title="Start Live Mode"
      >
        <p className="text-sm text-text-primary mb-4">
          Live mode spends real SOL. Continue?
        </p>
        <div className="flex justify-end gap-2">
          <button
            onClick={() => setShowLiveConfirm(false)}
            className="px-3 py-1.5 text-xs border border-border rounded hover:bg-bg-active transition-colors text-text-secondary"
          >
            No, cancel
          </button>
          <button
            onClick={() => {
              setShowLiveConfirm(false);
              void doStart();
            }}
            className="px-3 py-1.5 text-xs bg-accent-green/20 text-accent-green rounded hover:bg-accent-green/30 transition-colors"
          >
            Yes, start live
          </button>
        </div>
      </Modal>
    </>
  );
}
