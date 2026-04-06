"""BacktestRunner — async backtest execution with progress tracking."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import polars as pl
import structlog

from mev_kit.adapters.ingest.merged_replay import MergedReplayAdapter
from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.simulators.fill_simulator import FillSimulator
from mev_kit.adapters.sinks.paper_trade import BacktestSink
from mev_kit.models import ExecutionMode, PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.base import Detector
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()

# Registry of built-in strategies
STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"

# Default path for backtest result databases
DEFAULT_BACKTEST_DB = "./data/backtest_results.db"


def detect_source_type(data_path: str) -> str:
    """Auto-detect source_type from a Parquet file's column schema.

    Returns:
        "pool" if the file has pool-specific columns (pool_address),
        "price" if it has OHLCV columns (open, high, low, close),
        "price" if it has a 'symbol' column with a 'price' column,
        "pool" as fallback.
    """
    try:
        schema = pl.read_parquet_schema(data_path)
        columns = set(schema.keys()) if isinstance(schema, dict) else set(schema)
    except Exception:
        return "pool"

    # Merged backtest data (has both dex_price and cex_price)
    if "dex_price" in columns and "cex_price" in columns:
        return "merged"

    # OHLCV data (Binance klines)
    ohlcv_cols = {"open", "high", "low", "close"}
    if ohlcv_cols.issubset(columns):
        return "price"

    # Pool/DEX data
    if "pool_address" in columns:
        return "pool"

    # Generic price data (symbol + price)
    if "symbol" in columns and "price" in columns:
        return "price"

    return "pool"


class BacktestRunner:
    """Runs backtests and tracks progress."""

    def __init__(self) -> None:
        self._state: str = "idle"
        self._pipeline: Pipeline | None = None
        self._task: asyncio.Task | None = None
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

        # Cancel any orphaned tasks from previous runs
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

        self._state = "running"

        # Use FillSimulator for realistic execution modeling
        venue = config.get("venue", "aggregated")
        simulate_fills = config.get("simulate_fills", True)

        pipeline_config = PipelineConfig(
            mode=ExecutionMode.BACKTEST,
            simulate_before_execute=simulate_fills,
            min_spread_bps=config.get("min_spread_bps", 15.0),
            position_size_sol=config.get("position_size_sol", 0.01),
            circuit_breaker_enabled=False,
        )

        # Build adapters — support single file, dual file, or merged
        adapters = []
        source_type = detect_source_type(data_path)
        logger.info(
            "backtest_runner.source_type_detected",
            data_path=data_path,
            source_type=source_type,
        )

        if source_type == "merged":
            # Merged dataset — single adapter emits both DEX and CEX in time order
            # use_sources filters which sources to emit (empty = all)
            use_sources = config.get("use_sources", [])
            adapters.append(MergedReplayAdapter({"path": data_path, "use_sources": use_sources}))
            logger.info("backtest_runner.using_merged_adapter", data_path=data_path)
        else:
            # Standard single-source replay
            adapters.append(ParquetReplayAdapter({"path": data_path, "source_type": source_type}))

            # If a second data file is provided (for dual-source strategies like CEX-DEX arb)
            cex_data = config.get("cex_data_file", "")
            if cex_data and "/" not in cex_data:
                # Prepend data dir for bare filenames
                data_dir = Path(data_path).parent
                cex_data = str(data_dir / cex_data)
            if cex_data:
                cex_source = detect_source_type(cex_data)
                logger.info("backtest_runner.cex_source_detected", path=cex_data, source_type=cex_source)
                # Tag CEX replay data as BINANCE_WS so the detector treats it as CEX prices
                adapters.append(ParquetReplayAdapter({
                    "path": cex_data,
                    "source_type": cex_source,
                    "source_override": "binance_ws",
                }))
        detector = _load_detector(
            config.get("strategy", "price_momentum"),
            {
                "min_spread_bps": pipeline_config.min_spread_bps,
                "fee_bps": config.get("fee_bps", 30.0),
                "pair": "SOL/USDC",
                "position_size_sol": pipeline_config.position_size_sol,
            },
        )
        if simulate_fills:
            simulator = FillSimulator({
                "venue": venue,
                "landing_model": config.get("landing_model", "stochastic"),
                "random_seed": config.get("random_seed"),
            })
        else:
            simulator = PassthroughSimulator({})
        self._sink = BacktestSink({"output_path": None})

        self._pipeline = Pipeline(
            config=pipeline_config,
            adapters=adapters,
            detector=detector,
            simulator=simulator,
            sink=self._sink,
        )

        try:
            await self._pipeline.run()
            self._state = "completed"
            self._results = self._compute_results()
            # Persist results to SQLite for the Analysis page (Fix 4)
            db_path = config.get("results_db", DEFAULT_BACKTEST_DB)
            await self._persist_results_to_sqlite(db_path)
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
                "message": (
                    "No opportunities detected. This usually means: "
                    "(1) the strategy requires data columns not present in this file, "
                    "(2) min_spread_bps is set higher than any spread in the data, "
                    "or (3) the data window is too short. "
                    "Try a different strategy or adjust parameters."
                ),
            }

        from mev_kit.utils.precision import ProfitAccumulator, sol_to_lamports

        results = self._sink.results

        # Accumulate P&L in integer lamports to avoid float drift
        acc = ProfitAccumulator()
        for r in results:
            profit_lam = sol_to_lamports(r.get("simulated_profit_sol", 0))
            acc.add(profit_lam)

        # Spread aggregation (integer bps × 10 for 1 decimal precision)
        spread_sum = sum(int(r.get("spread_bps", 0) * 10) for r in results)
        avg_spread = (spread_sum / max(1, len(results))) / 10

        result = {
            "total_trades": acc.count,
            "total_profit_sol": round(acc.total_sol, 6),
            "avg_profit_sol": round(acc.avg_sol, 6),
            "win_rate": round(acc.win_rate, 4),
            "best_trade_sol": round(acc.best_sol, 6),
            "worst_trade_sol": round(acc.worst_sol, 6),
            "avg_spread_bps": round(avg_spread, 1),
            "trades": results,
        }

        # Include fill simulation stats if FillSimulator was used
        if self._pipeline and hasattr(self._pipeline.simulator, "_total_simulated"):
            sim = self._pipeline.simulator
            result["fill_stats"] = {
                "venue": getattr(sim, "venue_name", "unknown"),
                "venue_label": sim.venue.get("label", "Unknown"),
                "total_simulated": sim._total_simulated,
                "total_landed": sim._total_landed,
                "landing_rate_actual": round(
                    sim._total_landed / max(1, sim._total_simulated), 4
                ),
                "landing_rate_model": sim.venue.get("landing_rate", 0),
                "fee_bps": sim.venue.get("fee_bps", 0),
                "avg_slippage_bps": sim.venue.get("base_slippage_bps", 0),
            }

        return result

    async def _persist_results_to_sqlite(self, db_path: str) -> None:
        """Write backtest results to SQLite for the Analysis page.

        Uses the same schema as PaperTradeSink so the Analysis
        endpoints can query backtest and paper-trade results
        with identical queries.
        """
        if not self._sink or not self._sink.results:
            return

        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        type TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        pair TEXT NOT NULL,
                        dex TEXT NOT NULL,
                        dex_price REAL NOT NULL,
                        reference_price REAL NOT NULL,
                        spread_bps REAL NOT NULL,
                        estimated_profit_sol REAL NOT NULL,
                        simulated_profit_sol REAL NOT NULL,
                        pool_address TEXT,
                        detector TEXT,
                        metadata TEXT
                    )
                """)

                # Batch insert with executemany for performance on large trade counts
                rows = [
                    (
                        r["id"],
                        r.get("detected_at", datetime.utcnow().isoformat()),
                        r["type"],
                        r["direction"],
                        r["pair"],
                        r["dex"],
                        r["dex_price"],
                        r["reference_price"],
                        r["spread_bps"],
                        r["estimated_profit_sol"],
                        r["simulated_profit_sol"],
                        r.get("slot", ""),
                        "backtest",
                        json.dumps(r),
                    )
                    for r in self._sink.results
                ]
                await db.executemany(
                    """INSERT OR IGNORE INTO paper_trades
                       (id, timestamp, type, direction, pair, dex, dex_price,
                        reference_price, spread_bps, estimated_profit_sol,
                        simulated_profit_sol, pool_address, detector, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                await db.commit()
            logger.info(
                "backtest_runner.results_persisted",
                db_path=db_path,
                trade_count=len(self._sink.results),
            )
        except Exception as exc:
            logger.warning("backtest_runner.persist_failed", error=str(exc))


def _load_detector(strategy: str, config: dict) -> Detector:
    """Load a detector by name or file path.

    Supports:
        - "cex_dex_arb" — built-in CEX-DEX arb detector
        - "price_momentum" — single-source price momentum detector
        - "examples/spread_tracker" — example detector
        - "my_detector.py" — user strategy file in strategies dir
    """
    # Built-in strategies by short name
    builtins = {
        "cex_dex_arb": ("mev_kit.strategies.cex_dex_arb", "CEXDEXArbDetector"),
        "price_momentum": ("mev_kit.strategies.examples.price_momentum", "PriceMomentumDetector"),
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
        raise ValueError(f"Strategy not found: '{strategy}'. Available: {', '.join(builtins.keys())}")

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
