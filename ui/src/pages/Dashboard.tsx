import { useState } from "react";
import { ResponsiveGridLayout, useContainerWidth } from "react-grid-layout";
import type { ResponsiveLayouts } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

import { usePipeline } from "../hooks/usePipeline";
import MetricsStrip from "../components/panels/MetricsStrip";
import PnlChart from "../components/panels/PnlChart";
import SpreadHistogram from "../components/panels/SpreadHistogram";
import OpportunityFeed from "../components/panels/OpportunityFeed";
import LivePrices from "../components/panels/LivePrices";
import HotParams from "../components/panels/HotParams";
import LogStream from "../components/panels/LogStream";
import PipelineControls from "../components/panels/PipelineControls";

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

function DashboardGrid({
  metrics,
  state,
  mode,
  opportunities,
}: ReturnType<typeof usePipeline>) {
  const { width, containerRef, mounted } = useContainerWidth();
  const [layouts, setLayouts] = useState<ResponsiveLayouts>(getSavedLayouts);

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
    <div className="p-2 h-full flex flex-col">
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
                <LivePrices dexPrice={null} cexPrice={null} />
                <HotParams />
                <div className="flex-1 min-h-0">
                  <LogStream />
                </div>
              </div>
            </div>
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const pipeline = usePipeline();
  return <DashboardGrid {...pipeline} />;
}
