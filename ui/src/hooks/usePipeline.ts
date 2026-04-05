import { useCallback, useEffect, useRef, useState } from "react";
import type { Opportunity, PipelineMetrics, WsMessage } from "../api/types";
import { useWebSocket } from "./useWebSocket";

export function usePipeline() {
  const { data, connected } = useWebSocket<WsMessage>("/api/pipeline/ws");
  const [metrics, setMetrics] = useState<PipelineMetrics | null>(null);
  const [state, setState] = useState<string>("idle");
  const [mode, setMode] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [dexPrice, setDexPrice] = useState<number | null>(null);
  const [cexPrice, setCexPrice] = useState<number | null>(null);
  const maxOpps = useRef(200);

  useEffect(() => {
    if (!data) return;
    if (data.type === "metrics") {
      setMetrics(data.data as unknown as PipelineMetrics);
      setState(data.state ?? "idle");
      setMode(data.mode ?? null);
      // Track error state
      setError(data.error ?? null);
      // Track live prices if present in metrics payload
      if (data.dex_price != null) setDexPrice(data.dex_price);
      if (data.cex_price != null) setCexPrice(data.cex_price);
    }
    if (data.type === "opportunity") {
      setOpportunities((prev) => {
        const next = [data.data as unknown as Opportunity, ...prev];
        return next.slice(0, maxOpps.current);
      });
    }
  }, [data]);

  const clearOpportunities = useCallback(() => setOpportunities([]), []);
  const clearError = useCallback(() => setError(null), []);

  return {
    metrics,
    state,
    mode,
    opportunities,
    connected,
    clearOpportunities,
    error,
    clearError,
    dexPrice,
    cexPrice,
  };
}
