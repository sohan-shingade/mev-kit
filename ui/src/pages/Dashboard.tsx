import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ResponsiveGridLayout, useContainerWidth } from "react-grid-layout";
import type { ResponsiveLayouts } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { X } from "lucide-react";

import { usePipeline } from "../hooks/usePipeline";
import { get } from "../api/client";
import type { DataFile } from "../api/types";
import MetricsStrip from "../components/panels/MetricsStrip";
import PnlChart from "../components/panels/PnlChart";
import SpreadHistogram from "../components/panels/SpreadHistogram";
import OpportunityFeed from "../components/panels/OpportunityFeed";
import LivePrices from "../components/panels/LivePrices";
import HotParams from "../components/panels/HotParams";
import LogStream from "../components/panels/LogStream";
import PipelineControls from "../components/panels/PipelineControls";

const ONBOARDING_DISMISSED_KEY = "mev-kit-onboarding-dismissed";

const DEFAULT_LAYOUTS: ResponsiveLayouts = {
  lg: [
    { i: "pnl", x: 0, y: 0, w: 8, h: 4 },
    { i: "spread", x: 8, y: 0, w: 4, h: 4 },
    { i: "feed", x: 0, y: 4, w: 8, h: 5 },
    { i: "sidebar", x: 8, y: 4, w: 4, h: 5 },
  ],
};

function getSavedLayouts(): ResponsiveLayouts {
  try {
    const saved = localStorage.getItem("mev-kit-dashboard-layouts");
    if (saved) return JSON.parse(saved) as ResponsiveLayouts;
  } catch {
    /* use defaults */
  }
  return DEFAULT_LAYOUTS;
}

// Onboarding banner shown when no data files exist and pipeline is idle
function OnboardingBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="mx-2 mt-2 rounded-md bg-accent-indigo/10 border border-accent-indigo/50 px-4 py-3 flex items-start gap-3">
      <div className="flex-1">
        <p className="text-xs font-semibold text-accent-indigo mb-2 uppercase tracking-wider">
          Get started with mev-kit
        </p>
        <ol className="flex items-center gap-1 text-xs text-text-primary flex-wrap">
          <li>
            <Link
              to="/data"
              className="text-accent-indigo hover:underline font-medium"
            >
              1. Fetch data
            </Link>
          </li>
          <li className="text-text-secondary mx-1">→</li>
          <li>
            <Link
              to="/backtest"
              className="text-accent-indigo hover:underline font-medium"
            >
              2. Run a backtest
            </Link>
          </li>
          <li className="text-text-secondary mx-1">→</li>
          <li>
            <Link
              to="/analysis"
              className="text-accent-indigo hover:underline font-medium"
            >
              3. Analyze results
            </Link>
          </li>
        </ol>
      </div>
      <button
        onClick={onDismiss}
        title="Dismiss"
        className="text-text-secondary hover:text-text-primary transition-colors mt-0.5"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// Error banner shown when pipeline state is "error"
function ErrorBanner({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="mx-2 mt-2 rounded-md bg-accent-red/10 border border-accent-red/50 px-4 py-2 flex items-center gap-3">
      <span className="flex-1 text-xs text-accent-red">{message}</span>
      <button
        onClick={onDismiss}
        title="Dismiss"
        className="text-accent-red/60 hover:text-accent-red transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  );
}

function DashboardGrid(props: ReturnType<typeof usePipeline>) {
  const { metrics, state, mode, opportunities, error, clearError, dexPrice, cexPrice } = props;
  const { width, containerRef, mounted } = useContainerWidth();
  const [layouts, setLayouts] = useState<ResponsiveLayouts>(getSavedLayouts);

  // Onboarding banner state
  const [showOnboarding, setShowOnboarding] = useState(false);

  useEffect(() => {
    // Don't show if already dismissed
    if (localStorage.getItem(ONBOARDING_DISMISSED_KEY)) return;
    // Only show when pipeline is idle
    if (state !== "idle") return;

    // Check if data files exist
    get<DataFile[]>("/api/data/files")
      .then((files) => {
        if (files.length === 0) setShowOnboarding(true);
      })
      .catch(() => {
        // Server not ready — don't show banner
      });
  }, [state]);

  const handleDismissOnboarding = () => {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
    setShowOnboarding(false);
  };

  const handleLayoutChange = (
    _layout: unknown,
    allLayouts: ResponsiveLayouts
  ) => {
    setLayouts(allLayouts);
    localStorage.setItem(
      "mev-kit-dashboard-layouts",
      JSON.stringify(allLayouts)
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* Onboarding banner */}
      {showOnboarding && (
        <OnboardingBanner onDismiss={handleDismissOnboarding} />
      )}

      {/* Pipeline error banner */}
      {state === "error" && error && (
        <ErrorBanner message={error} onDismiss={clearError} />
      )}

      <div className="p-2 flex-1 flex flex-col min-h-0">
        {/* Top bar: controls + metrics */}
        <div className="flex items-center gap-2 mb-0.5">
          <PipelineControls state={state} mode={mode} />
          <div className="flex-1">
            <MetricsStrip metrics={metrics} state={state} mode={mode} />
          </div>
        </div>

        {/* Grid panels */}
        <div className="flex-1" ref={containerRef}>
          {mounted && (
            <ResponsiveGridLayout
              width={width}
              layouts={layouts}
              breakpoints={{ lg: 1200, md: 996, sm: 768 }}
              cols={{ lg: 12, md: 10, sm: 6 }}
              rowHeight={40}
              onLayoutChange={handleLayoutChange}
              compactor={undefined}
            >
              <div key="pnl">
                <PnlChart opportunities={opportunities} />
              </div>
              <div key="spread">
                <SpreadHistogram opportunities={opportunities} />
              </div>
              <div key="feed">
                <OpportunityFeed opportunities={opportunities} />
              </div>
              <div key="sidebar">
                <div className="h-full flex flex-col gap-0.5">
                  <LivePrices
                    dexPrice={dexPrice}
                    cexPrice={cexPrice}
                    pipelineRunning={state === "running"}
                  />
                  <HotParams configProfile="free" />
                  <div className="flex-1 min-h-0">
                    <LogStream />
                  </div>
                </div>
              </div>
            </ResponsiveGridLayout>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const pipeline = usePipeline();
  return <DashboardGrid {...pipeline} />;
}
