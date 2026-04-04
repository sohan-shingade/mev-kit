"""BacktestRunner — async backtest execution with progress tracking."""

from __future__ import annotations

from typing import Any

import structlog

from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import BacktestSink
from mev_kit.models import ExecutionMode, PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()


class BacktestRunner:
    """Runs backtests and tracks progress."""

    def __init__(self) -> None:
        self._state: str = "idle"
        self._pipeline: Pipeline | None = None
        self._sink: BacktestSink | None = None
        self._results: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        """Return current backtest state and results."""
        result: dict[str, Any] = {"state": self._state}
        if self._pipeline and self._state == "running":
            result["progress"] = {
                "updates_processed": self._pipeline.updates_processed,
                "opportunities_detected": self._pipeline.opportunities_detected,
            }
        if self._state == "completed":
            result["results"] = self._results
        return result

    async def run(self, data_path: str, config: dict) -> None:
        """Run a backtest against Parquet data."""
        self._state = "running"

        pipeline_config = PipelineConfig(
            mode=ExecutionMode.BACKTEST,
            simulate_before_execute=config.get("simulate_before_execute", False),
            min_spread_bps=config.get("min_spread_bps", 15.0),
            position_size_sol=config.get("position_size_sol", 0.01),
            circuit_breaker_enabled=False,
        )

        adapter = ParquetReplayAdapter({"path": data_path, "source_type": "pool"})
        detector = CEXDEXArbDetector({
            "min_spread_bps": pipeline_config.min_spread_bps,
            "fee_bps": config.get("fee_bps", 30.0),
            "pair": "SOL/USDC",
            "position_size_sol": pipeline_config.position_size_sol,
        })
        simulator = PassthroughSimulator({})
        self._sink = BacktestSink({"output_path": None})

        self._pipeline = Pipeline(
            config=pipeline_config,
            adapters=[adapter],
            detector=detector,
            simulator=simulator,
            sink=self._sink,
        )

        try:
            await self._pipeline.run()
        finally:
            self._state = "completed"
            self._results = self._compute_results()

    def _compute_results(self) -> dict[str, Any]:
        """Compute summary from backtest sink results."""
        if not self._sink or not self._sink.results:
            return {"total_trades": 0, "total_profit_sol": 0.0}

        results = self._sink.results
        profits = [r["simulated_profit_sol"] for r in results]
        return {
            "total_trades": len(results),
            "total_profit_sol": round(sum(profits), 6),
            "avg_profit_sol": round(sum(profits) / len(profits), 6) if profits else 0.0,
            "win_rate": round(sum(1 for p in profits if p > 0) / len(profits), 4) if profits else 0.0,
            "best_trade_sol": round(max(profits), 6) if profits else 0.0,
            "worst_trade_sol": round(min(profits), 6) if profits else 0.0,
            "avg_spread_bps": round(
                sum(r["spread_bps"] for r in results) / len(results), 1
            ) if results else 0.0,
            "trades": results,
        }
