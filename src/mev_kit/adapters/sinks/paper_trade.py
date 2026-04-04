"""Paper trade and backtest sink implementations.

These are the two $0-cost sinks that enable strategy validation
without spending any SOL.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from mev_kit.adapters.sinks.base import Sink
from mev_kit.models import ExecutionMode, ExecutionResult, Opportunity, SimulationResult


class PaperTradeSink(Sink):
    """Logs theoretical P&L to SQLite. No real transactions.

    Creates a SQLite database with a trades table. Every validated
    opportunity is recorded with its theoretical profit.

    Config keys:
        db_path (str): Path to SQLite database. Default: "./data/results.db"
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.db_path = config.get("db_path", "./data/results.db")
        self._db: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("""
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
        await self._db.commit()

    async def teardown(self) -> None:
        if self._db:
            await self._db.close()

    async def execute(
        self,
        opportunity: Opportunity,
        simulation: SimulationResult,
    ) -> ExecutionResult:
        self._executions += 1

        if self._db:
            await self._db.execute(
                """INSERT OR IGNORE INTO paper_trades
                   (id, timestamp, type, direction, pair, dex, dex_price,
                    reference_price, spread_bps, estimated_profit_sol,
                    simulated_profit_sol, pool_address, detector, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opportunity.id,
                    datetime.utcnow().isoformat(),
                    opportunity.type.value,
                    opportunity.direction.value,
                    opportunity.pair,
                    opportunity.dex,
                    opportunity.dex_price,
                    opportunity.reference_price,
                    opportunity.spread_bps,
                    opportunity.estimated_profit_sol,
                    simulation.net_profit_sol,
                    opportunity.pool_address,
                    opportunity.detector_name,
                    json.dumps(opportunity.metadata),
                ),
            )
            await self._db.commit()

        self._successes += 1

        return ExecutionResult(
            opportunity_id=opportunity.id,
            mode=ExecutionMode.PAPER,
            success=True,
            theoretical_profit_sol=simulation.net_profit_sol,
        )


class BacktestSink(Sink):
    """Accumulates results in memory for batch analysis after replay.

    Unlike PaperTradeSink which writes to SQLite row-by-row,
    BacktestSink collects all results and can export to Parquet
    or return as a Polars DataFrame.

    Config keys:
        output_path (str): Optional Parquet output path.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.output_path = config.get("output_path", None)
        self.results: list[dict] = []

    async def execute(
        self,
        opportunity: Opportunity,
        simulation: SimulationResult,
    ) -> ExecutionResult:
        self._executions += 1
        self._successes += 1

        record = {
            "id": opportunity.id,
            "type": opportunity.type.value,
            "direction": opportunity.direction.value,
            "pair": opportunity.pair,
            "dex": opportunity.dex,
            "dex_price": opportunity.dex_price,
            "reference_price": opportunity.reference_price,
            "spread_bps": opportunity.spread_bps,
            "estimated_profit_sol": opportunity.estimated_profit_sol,
            "simulated_profit_sol": simulation.net_profit_sol,
            "slot": opportunity.slot,
            "detected_at": opportunity.detected_at.isoformat(),
        }
        self.results.append(record)

        return ExecutionResult(
            opportunity_id=opportunity.id,
            mode=ExecutionMode.BACKTEST,
            success=True,
            theoretical_profit_sol=simulation.net_profit_sol,
        )

    async def teardown(self) -> None:
        """Export results to Parquet if output_path is set."""
        if self.output_path and self.results:
            try:
                import polars as pl

                df = pl.DataFrame(self.results)
                Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
                df.write_parquet(self.output_path)
            except ImportError:
                pass  # polars not installed, skip export
