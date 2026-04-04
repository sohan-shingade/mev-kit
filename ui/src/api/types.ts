export interface PipelineStatus {
  state: "idle" | "running" | "stopping";
  mode: string | null;
  metrics: PipelineMetrics;
}

export interface PipelineMetrics {
  updates_processed: number;
  opportunities_detected: number;
  opportunities_simulated: number;
  opportunities_profitable: number;
  opportunities_executed: number;
  total_profit_sol: number;
  consecutive_misses: number;
  detection_rate: number;
  elapsed_seconds: number;
  queue_size: number;
}

export interface Opportunity {
  id: string;
  type: string;
  direction: "BUY_DEX" | "SELL_DEX";
  spread_bps: number;
  estimated_profit_sol: number;
  simulated_profit_sol: number;
  sim_latency_ms: number;
  success: boolean;
  timestamp: string;
}

export interface ConfigProfile {
  pipeline: Record<string, unknown>;
  strategy: Record<string, unknown>;
  ingest?: Record<string, unknown>;
  simulator?: Record<string, unknown>;
  sink?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  data?: Record<string, unknown>;
}

export interface DataFile {
  name: string;
  size_bytes: number;
  rows: number;
  columns: string[];
  modified: number;
}

export interface Guide {
  slug: string;
  title: string;
}

export interface TradeRow {
  id: string;
  timestamp: string;
  detected_at?: string;
  type: string;
  direction: string;
  pair: string;
  dex: string;
  dex_price: number;
  reference_price: number;
  spread_bps: number;
  estimated_profit_sol: number;
  simulated_profit_sol: number;
  pool_address: string;
  detector: string;
}

export interface BacktestStatus {
  state: "idle" | "running" | "completed" | "error";
  progress?: { updates_processed: number; opportunities_detected: number };
  results?: BacktestResults;
}

export interface BacktestResults {
  total_trades: number;
  total_profit_sol: number;
  avg_profit_sol: number;
  win_rate: number;
  best_trade_sol: number;
  worst_trade_sol: number;
  avg_spread_bps: number;
  trades: TradeRow[];
}

export interface AnalysisSummary {
  total_trades: number;
  total_profit_sol: number;
  avg_profit_sol: number;
  best_trade_sol: number;
  worst_trade_sol: number;
  avg_spread_bps: number;
  first_trade: string;
  last_trade: string;
  win_rate: number;
}

export interface WsMessage {
  type: "metrics" | "opportunity" | "log";
  data: Record<string, unknown>;
  state?: string;
  mode?: string | null;
}
