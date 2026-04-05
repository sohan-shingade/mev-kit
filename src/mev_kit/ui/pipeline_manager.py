"""PipelineManager — singleton that owns the running Pipeline instance.

Provides start/stop/status/hot-reload for the web UI. Pushes metrics
over async generators for WebSocket consumers.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator, Simulator
from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
from mev_kit.adapters.sinks.jito_bundle import JitoBundleSink
from mev_kit.adapters.sinks.paper_trade import PaperTradeSink
from mev_kit.models import PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()

# Hot-reloadable params that can be patched on a live detector
HOT_PARAMS = {"min_spread_bps", "fee_bps", "position_size_sol", "max_position_size_sol"}



class PipelineManager:
    """Singleton managing the running Pipeline instance."""

    _instance: PipelineManager | None = None

    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._task: asyncio.Task | None = None
        self._mode: str | None = None
        self._start_time: float | None = None
        self._recent_opportunities: list[dict] = []
        self._max_recent = 200
        self._error: str | None = None

    @classmethod
    def get(cls) -> PipelineManager:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        """Return current pipeline state and metrics."""
        if self._pipeline is None or self._task is None:
            base = {"state": "idle", "mode": None, "metrics": {}}
            if self._error:
                base["state"] = "error"
                base["error"] = self._error
            return base

        if self._task.done():
            # Check if the task ended with an exception
            exc = self._task.exception() if not self._task.cancelled() else None
            if exc is not None:
                self._error = str(exc)
                return {
                    "state": "error",
                    "mode": self._mode,
                    "metrics": {},
                    "error": self._error,
                }
            return {"state": "idle", "mode": None, "metrics": {}}

        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        p = self._pipeline
        updates = p.updates_processed
        detected = p.opportunities_detected

        return {
            "state": "running",
            "mode": self._mode,
            "metrics": {
                "updates_processed": updates,
                "opportunities_detected": detected,
                "opportunities_simulated": p.opportunities_simulated,
                "opportunities_profitable": p.opportunities_profitable,
                "opportunities_executed": p.opportunities_executed,
                "total_profit_sol": round(p.total_profit_sol, 6),
                "consecutive_misses": p.consecutive_misses,
                "detection_rate": round(detected / max(1, updates), 4),
                "elapsed_seconds": round(elapsed, 1),
                "queue_size": p._update_queue.qsize(),
            },
        }

    async def start(self, mode: str, config_overrides: dict) -> None:
        """Start the pipeline in the given mode."""
        if self._pipeline is not None and self._task is not None and not self._task.done():
            raise RuntimeError("Pipeline already running")

        self._error = None  # Clear previous error on new start
        pipeline = _build_pipeline(mode, config_overrides)
        self._pipeline = pipeline
        self._mode = mode
        self._start_time = time.monotonic()
        self._recent_opportunities = []
        self._task = asyncio.create_task(pipeline.run())
        logger.info("pipeline_manager.started", mode=mode)

    async def stop(self) -> None:
        """Stop the running pipeline."""
        if self._pipeline is None:
            return
        await self._pipeline.stop()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except TimeoutError:
                self._task.cancel()
        self._pipeline = None
        self._task = None
        self._mode = None
        self._start_time = None
        self._error = None
        logger.info("pipeline_manager.stopped")

    def hot_reload(self, params: dict) -> None:
        """Patch hot-reloadable params on the live detector."""
        if self._pipeline is None:
            raise RuntimeError("No pipeline running")
        detector = self._pipeline.detector
        for key, value in params.items():
            if key in HOT_PARAMS and hasattr(detector, key):
                setattr(detector, key, value)
                logger.info("pipeline_manager.hot_reload", param=key, value=value)

    def add_opportunity(self, opp: dict) -> None:
        """Track a recent opportunity for the feed."""
        self._recent_opportunities.insert(0, opp)
        if len(self._recent_opportunities) > self._max_recent:
            self._recent_opportunities.pop()

    @property
    def recent_opportunities(self) -> list[dict]:
        return list(self._recent_opportunities)


def _build_pipeline(mode: str, config_overrides: dict) -> Pipeline:
    """Build a Pipeline from mode and config overrides."""
    config = PipelineConfig(mode=mode, **{
        k: v for k, v in config_overrides.items()
        if k in PipelineConfig.model_fields
    })

    # Build adapters based on mode
    adapters = []
    helius_key = os.environ.get("HELIUS_API_KEY", config.helius_api_key)

    if mode in ("paper", "live"):
        if helius_key:
            adapters.append(HeliusWSAdapter({"helius_api_key": helius_key}))
        adapters.append(BinanceWSAdapter({"symbol": "solusdt"}))

    # Use _load_detector to support any registered strategy name
    strategy_name = config_overrides.get("strategy", config.strategy)
    detector_config = {
        "min_spread_bps": config.min_spread_bps,
        "fee_bps": config_overrides.get("fee_bps", 30.0),
        "pair": "SOL/USDC",
        "position_size_sol": config.position_size_sol,
    }

    try:
        from mev_kit.ui.backtest_runner import _load_detector
        detector = _load_detector(strategy_name, detector_config)
    except Exception:
        logger.warning(
            "pipeline_manager.detector_load_failed",
            strategy=strategy_name,
        )
        detector = CEXDEXArbDetector(detector_config)

    # Simulator
    if config.simulate_before_execute and mode != "backtest":
        rpc_url = os.environ.get("HELIUS_RPC_URL", config.helius_rpc_url)
        simulator: Simulator = RPCSimulator({"rpc_url": rpc_url})
    else:
        simulator = PassthroughSimulator({})

    # Sink
    if mode == "live":
        sink = JitoBundleSink({
            "jito_url": config.jito_block_engine_url,
            "tip_percentage": config.tip_percentage,
            "keypair_path": os.environ.get("WALLET_KEYPAIR_PATH", ""),
            "dry_run": config_overrides.get("dry_run", False),
        })
    else:
        sink = PaperTradeSink({"db_path": config.results_db})

    return Pipeline(
        config=config,
        adapters=adapters,
        detector=detector,
        simulator=simulator,
        sink=sink,
    )
