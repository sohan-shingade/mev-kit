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

export interface FillStats {
  venue: string;
  venue_label: string;
  total_simulated: number;
  total_landed: number;
  landing_rate_actual: number;
  landing_rate_model: number;
  fee_bps: number;
  avg_slippage_bps: number;
}

export interface CostBreakdown {
  avg_venue_fee_bps: number;
  avg_slippage_bps: number;
  avg_staleness_bps: number;
  avg_tip_bps: number;
  landing_rate: number;
}

export interface EquityCurvePoint {
  timestamp: string;
  pnl: number;
  drawdown: number;
  high_water: number;
}

export interface RiskMetrics {
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  profit_factor: number;
  max_drawdown_sol: number;
  max_drawdown_duration: number;
  avg_win_sol: number;
  avg_loss_sol: number;
  max_win_streak: number;
  max_loss_streak: number;
  gross_profit_sol: number;
  gross_loss_sol: number;
}

export interface HourlyBreakdown {
  hour: number;
  trade_count: number;
  total_pnl: number;
  win_rate: number;
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
  message?: string;
  fill_stats?: FillStats;
  cost_breakdown?: CostBreakdown;
  warnings?: string[];
  equity_curve?: EquityCurvePoint[];
  risk_metrics?: RiskMetrics;
  hourly_breakdown?: HourlyBreakdown[];
  run_id?: string;
  run_timestamp?: string;
  run_config?: Record<string, unknown>;
}

export interface SweepResultRow {
  params: Record<string, number>;
  total_trades: number;
  total_profit_sol: number;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown_sol: number;
  profit_factor: number;
  avg_spread_bps: number;
  error?: string;
}

export interface SweepStatus {
  state: "idle" | "running" | "completed" | "error";
  progress: number;
  total: number;
  current_params?: Record<string, number>;
  results?: SweepResultRow[];
}

export interface WalkForwardResult {
  type: "walk_forward";
  train_results: SweepResultRow[];
  best_params: Record<string, number>;
  in_sample: {
    trades: number;
    profit_sol: number;
    sharpe: number;
    drawdown: number;
  };
  out_of_sample: {
    trades: number;
    profit_sol: number;
    sharpe: number;
    drawdown: number;
  };
  overfit_warning: boolean;
  train_pct: number;
  train_rows: number;
  test_rows: number;
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
  error?: string | null;
  dex_price?: number | null;
  cex_price?: number | null;
}
