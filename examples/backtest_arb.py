"""Minimal backtest example — 20 lines to run a full MEV backtest.

Usage:
    python examples/backtest_arb.py ./data/raydium_sol_usdc.parquet
"""

import asyncio
import sys

from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import BacktestSink
from mev_kit.models import PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector


async def main(data_path: str) -> None:
    pipeline = Pipeline(
        config=PipelineConfig(mode="backtest", simulate_before_execute=False),
        adapters=[ParquetReplayAdapter({"path": data_path, "source_type": "pool"})],
        detector=CEXDEXArbDetector({"min_spread_bps": 15.0, "position_size_sol": 1.0}),
        simulator=PassthroughSimulator({}),
        sink=BacktestSink({"output_path": "./data/backtest_results.parquet"}),
    )
    await pipeline.run()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "./data/sample.parquet"))
