"""BacktestRunner — async backtest execution with progress tracking."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import structlog

from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import BacktestSink
from mev_kit.models import ExecutionMode, PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.base import Detector
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()

# Registry of built-in strategies
STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"


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
        if self._state in ("completed", "error"):
            result["results"] = self._results
        return result

    async def run(self, data_path: str, config: dict) -> None:
        """Run a backtest against Parquet data."""
        if self._state == "running":
            raise RuntimeError("Backtest already running")
        self._state = "running"

        pipeline_config = PipelineConfig(
            mode=ExecutionMode.BACKTEST,
            simulate_before_execute=config.get("simulate_before_execute", False),
            min_spread_bps=config.get("min_spread_bps", 15.0),
            position_size_sol=config.get("position_size_sol", 0.01),
            circuit_breaker_enabled=False,
        )

        adapter = ParquetReplayAdapter({"path": data_path, "source_type": "pool"})
        detector = _load_detector(
            config.get("strategy", "cex_dex_arb"),
            {
                "min_spread_bps": pipeline_config.min_spread_bps,
                "fee_bps": config.get("fee_bps", 30.0),
                "pair": "SOL/USDC",
                "position_size_sol": pipeline_config.position_size_sol,
            },
        )
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
            self._state = "completed"
            self._results = self._compute_results()
        except Exception as exc:
            self._state = "error"
            self._results = {
                "total_trades": 0,
                "total_profit_sol": 0.0,
                "avg_profit_sol": 0.0,
                "win_rate": 0.0,
                "best_trade_sol": 0.0,
                "worst_trade_sol": 0.0,
                "avg_spread_bps": 0.0,
                "trades": [],
                "error": str(exc),
            }

    def _compute_results(self) -> dict[str, Any]:
        """Compute summary from backtest sink results."""
        if not self._sink or not self._sink.results:
            return {
                "total_trades": 0,
                "total_profit_sol": 0.0,
                "avg_profit_sol": 0.0,
                "win_rate": 0.0,
                "best_trade_sol": 0.0,
                "worst_trade_sol": 0.0,
                "avg_spread_bps": 0.0,
                "trades": [],
            }

        results = self._sink.results
        profits = [r["simulated_profit_sol"] for r in results]
        return {
            "total_trades": len(results),
            "total_profit_sol": round(sum(profits), 6),
            "avg_profit_sol": round(sum(profits) / len(profits), 6) if profits else 0.0,
            "win_rate": round(
                sum(1 for p in profits if p > 0) / len(profits), 4
            ) if profits else 0.0,
            "best_trade_sol": round(max(profits), 6) if profits else 0.0,
            "worst_trade_sol": round(min(profits), 6) if profits else 0.0,
            "avg_spread_bps": round(
                sum(r["spread_bps"] for r in results) / len(results), 1
            ) if results else 0.0,
            "trades": results,
        }


def _load_detector(strategy: str, config: dict) -> Detector:
    """Load a detector by name or file path.

    Supports:
        - "cex_dex_arb" — built-in CEX-DEX arb detector
        - "examples/spread_tracker" — example detector
        - "my_detector.py" — user strategy file in strategies dir
    """
    # Built-in strategies by short name
    builtins = {
        "cex_dex_arb": ("mev_kit.strategies.cex_dex_arb", "CEXDEXArbDetector"),
        "spread_tracker": ("mev_kit.strategies.examples.spread_tracker", "SpreadTracker"),
        "multi_pool_arb": ("mev_kit.strategies.examples.multi_pool_arb", "MultiPoolArbDetector"),
        "liquidation_detector": ("mev_kit.strategies.examples.liquidation_detector", "LiquidationDetector"),
        "statistical_arb": ("mev_kit.strategies.examples.statistical_arb", "StatisticalArbDetector"),
        "momentum_detector": ("mev_kit.strategies.examples.momentum_detector", "MomentumDetector"),
    }

    # Clean up the name
    name = strategy.replace(".py", "").replace("examples/", "")

    if name in builtins:
        module_path, class_name = builtins[name]
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(config)

    # Try loading from a .py file in the strategies directory
    file_path = STRATEGIES_DIR / f"{name}.py"
    if not file_path.exists():
        file_path = STRATEGIES_DIR / strategy  # try with .py extension
    if not file_path.exists():
        logger.warning("backtest_runner.strategy_not_found", strategy=strategy)
        return CEXDEXArbDetector(config)  # fallback

    # Dynamic import from file
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Find the first Detector subclass in the module
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Detector)
                and attr is not Detector
            ):
                return attr(config)

    logger.warning("backtest_runner.no_detector_in_file", file=str(file_path))
    return CEXDEXArbDetector(config)
