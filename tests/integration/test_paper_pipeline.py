"""Integration test for the full paper-trade pipeline.

Uses ParquetReplayAdapter with synthetic test data to verify the
complete pipeline: ingest -> detect -> simulate -> sink.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import polars as pl
import pytest

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import PaperTradeSink
from mev_kit.models import ExecutionMode, PipelineConfig, PriceUpdate, Source, StateUpdate
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector


class CexReplayAdapter(IngestAdapter):
    """Replays price data from Parquet as Binance CEX updates.

    Wraps ParquetReplayAdapter but emits Source.BINANCE_WS so the
    CEXDEXArbDetector treats the data as CEX reference prices.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._inner = ParquetReplayAdapter(config)

    async def connect(self) -> None:
        await self._inner.connect()
        self._running = True

    async def disconnect(self) -> None:
        self._running = False
        await self._inner.disconnect()

    async def stream(self) -> AsyncIterator[StateUpdate]:
        self._inner._running = True
        async for update in self._inner.stream():
            if not self._running:
                break
            # Re-tag as Binance CEX source
            if update.price:
                yield StateUpdate(
                    source=Source.BINANCE_WS,
                    price=PriceUpdate(
                        symbol=update.price.symbol,
                        price=update.price.price,
                        volume=update.price.volume,
                        source=Source.BINANCE_WS,
                        timestamp=update.price.timestamp,
                    ),
                    received_at=update.received_at,
                )


def _create_dex_parquet(path: str) -> None:
    """Create synthetic DEX pool state data."""
    rows = []
    base_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    for i in range(20):
        ts = base_time.replace(second=i * 3)
        # DEX price drops from 148.0 to 146.0 at i=10, creating arb opportunity
        dex_price = 148.0 if i < 10 else 146.0
        base_reserve = 1000.0
        quote_reserve = dex_price * base_reserve

        rows.append({
            "pool_address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "dex": "raydium",
            "base_mint": "So11111111111111111111111111111111111111112",
            "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "base_reserve": base_reserve,
            "quote_reserve": quote_reserve,
            "price": dex_price,
            "fee_bps": 30,
            "slot": 280_000_000 + i,
            "timestamp": ts,
        })

    pl.DataFrame(rows).write_parquet(path)


def _create_cex_parquet(path: str) -> None:
    """Create synthetic CEX price data.

    CEX price stays at 149.0 throughout — creating ~200bps spread
    against the 146.0 DEX price in the second half.
    """
    rows = []
    base_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    for i in range(20):
        ts = base_time.replace(second=i * 3 + 1)
        rows.append({
            "symbol": "SOL/USDC",
            "price": 149.0,
            "volume": 100.0,
            "source": "binance_ws",
            "timestamp": ts,
        })

    pl.DataFrame(rows).write_parquet(path)


class TestPaperPipeline:
    """Integration tests for the full paper-trade pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_replay(self) -> None:
        """Verify the complete pipeline: ingest -> detect -> simulate -> sink.

        Uses a ParquetReplayAdapter for DEX data and a CexReplayAdapter
        (emitting Source.BINANCE_WS) for CEX data. The DEX price drops
        in the second half, creating detectable arbitrage opportunities.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = os.path.join(tmpdir, "dex_data.parquet")
            cex_path = os.path.join(tmpdir, "cex_data.parquet")
            db_path = os.path.join(tmpdir, "test_results.db")

            _create_dex_parquet(dex_path)
            _create_cex_parquet(cex_path)

            # DEX adapter: emits Source.PARQUET_REPLAY (treated as DEX by detector)
            dex_adapter = ParquetReplayAdapter({
                "path": dex_path,
                "source_type": "pool",
            })

            # CEX adapter: wraps replay but emits Source.BINANCE_WS
            cex_adapter = CexReplayAdapter({
                "path": cex_path,
                "source_type": "price",
            })

            detector = CEXDEXArbDetector({
                "min_spread_bps": 15.0,
                "fee_bps": 30.0,
                "pair": "SOL/USDC",
                "position_size_sol": 1.0,
            })

            simulator = PassthroughSimulator({})
            sink = PaperTradeSink({"db_path": db_path})

            config = PipelineConfig(
                mode=ExecutionMode.PAPER,
                strategy="cex_dex_arb",
                simulate_before_execute=True,
                min_spread_bps=15.0,
                position_size_sol=1.0,
                results_db=db_path,
                circuit_breaker_enabled=False,
            )

            pipeline = Pipeline(
                config=config,
                adapters=[dex_adapter, cex_adapter],
                detector=detector,
                simulator=simulator,
                sink=sink,
            )

            await pipeline.run()

            # Verify results were written to SQLite
            assert Path(db_path).exists()

            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM paper_trades") as cursor:
                    count = (await cursor.fetchone())[0]

                assert count > 0, "Pipeline should have detected at least one opportunity"

                async with db.execute(
                    "SELECT type, direction, pair, dex_price, reference_price, spread_bps "
                    "FROM paper_trades LIMIT 1"
                ) as cursor:
                    row = await cursor.fetchone()
                    assert row[0] == "cex_dex_arb"
                    assert row[1] in ("buy_dex", "sell_dex")
                    assert row[2] == "SOL/USDC"
                    assert row[3] > 0  # dex_price
                    assert row[4] > 0  # reference_price
                    assert row[5] > 0  # spread_bps

            # Verify pipeline metrics
            assert pipeline.updates_processed > 0
            assert pipeline.opportunities_detected > 0
            assert pipeline.opportunities_executed > 0
