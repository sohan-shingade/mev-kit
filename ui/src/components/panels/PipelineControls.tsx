import { useState } from "react";
import { post } from "../../api/client";

interface Props {
  state: string;
  mode: string | null;
}

export default function PipelineControls({ state, mode }: Props) {
  const [selectedMode, setSelectedMode] = useState("paper");

  const handleStart = async () => {
    if (selectedMode === "live") {
      if (!confirm("⚠️ Live mode spends real SOL. Continue?")) return;
    }
    try {
      await post("/api/pipeline/start", { mode: selectedMode, config: {} });
    } catch {
      alert("Failed to start pipeline");
    }
  };

  const handleStop = async () => {
    if (mode === "live") {
      if (!confirm("Stop live pipeline?")) return;
    }
    try {
      await post("/api/pipeline/stop", {});
    } catch {
      alert("Failed to stop pipeline");
    }
  };

  if (state === "running") {
    return (
      <div className="flex items-center gap-2">
        <button
          onClick={handleStop}
          className="px-3 py-1 bg-accent-red/20 text-accent-red text-xs rounded hover:bg-accent-red/30 transition-colors"
        >
          Stop
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
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
  );
}
