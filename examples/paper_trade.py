"""Minimal paper trading example.

Connects to Helius (DEX pool data) and Binance (CEX prices)
via WebSocket and logs theoretical P&L to SQLite.

Requires HELIUS_API_KEY environment variable.

Usage:
    export HELIUS_API_KEY=your-key-here
    python examples/paper_trade.py
"""

import asyncio
import os
import signal

from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import PaperTradeSink
from mev_kit.models import PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector


async def main() -> None:
    api_key = os.environ["HELIUS_API_KEY"]

    pipeline = Pipeline(
        config=PipelineConfig(mode="paper", simulate_before_execute=False),
        adapters=[
            HeliusWSAdapter({"helius_api_key": api_key}),
            BinanceWSAdapter({"symbol": "solusdt"}),
        ],
        detector=CEXDEXArbDetector({
            "min_spread_bps": 15.0,
            "position_size_sol": 0.01,
        }),
        simulator=PassthroughSimulator({}),
        sink=PaperTradeSink({"db_path": "./data/results.db"}),
    )

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(pipeline.stop()))

    await pipeline.run()


if __name__ == "__main__":
    asyncio.run(main())
