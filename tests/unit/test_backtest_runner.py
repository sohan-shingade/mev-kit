"""Tests for BacktestRunner."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest

from mev_kit.ui.backtest_runner import BacktestRunner, detect_source_type


def _create_test_data(tmpdir: str) -> str:
    path = os.path.join(tmpdir, "test.parquet")
    rows = []
    for i in range(10):
        rows.append({
            "pool_address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "dex": "raydium",
            "base_mint": "SOL",
            "quote_mint": "USDC",
            "base_reserve": 1000.0,
            "quote_reserve": 148000.0 + i * 100,
            "price": 148.0 + i * 0.1,
            "fee_bps": 30,
            "slot": 280000000 + i,
            "timestamp": datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
        })
    pl.DataFrame(rows).write_parquet(path)
    return path


class TestBacktestRunner:

    def test_initial_state(self) -> None:
        runner = BacktestRunner()
        assert runner.status()["state"] == "idle"

    @pytest.mark.asyncio
    async def test_run_backtest_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_test_data(tmpdir)
            runner = BacktestRunner()
            await runner.run(
                data_path=data_path,
                config={"min_spread_bps": 15.0, "position_size_sol": 1.0},
            )
            status = runner.status()
            assert status["state"] == "completed"
            assert status["results"]["total_trades"] >= 0

    @pytest.mark.asyncio
    async def test_status_has_results_after_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_test_data(tmpdir)
            runner = BacktestRunner()
            await runner.run(data_path=data_path, config={})
            results = runner.status()["results"]
            assert "total_trades" in results
            assert "total_profit_sol" in results

    @pytest.mark.asyncio
    async def test_multi_asset_extra_data_files(self) -> None:
        """Extra data files should add additional adapters without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create primary data
            primary = _create_test_data(tmpdir)
            # Create extra data file
            extra_path = os.path.join(tmpdir, "extra.parquet")
            rows = []
            for i in range(5):
                rows.append({
                    "pool_address": "ExtraPoolAddr123",
                    "dex": "orca",
                    "base_mint": "ETH",
                    "quote_mint": "USDC",
                    "base_reserve": 500.0,
                    "quote_reserve": 1000000.0 + i * 50,
                    "price": 2000.0 + i * 0.5,
                    "fee_bps": 25,
                    "slot": 280000000 + i,
                    "timestamp": datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
                })
            pl.DataFrame(rows).write_parquet(extra_path)

            runner = BacktestRunner()
            await runner.run(
                data_path=primary,
                config={
                    "min_spread_bps": 15.0,
                    "extra_data_files": [extra_path],
                },
            )
            status = runner.status()
            assert status["state"] == "completed"
            assert "total_trades" in status["results"]

    @pytest.mark.asyncio
    async def test_multi_asset_bare_filename_resolved(self) -> None:
        """Bare filenames in extra_data_files should be resolved relative to primary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = _create_test_data(tmpdir)
            # Create second file in same directory
            extra_path = os.path.join(tmpdir, "second.parquet")
            rows = []
            for i in range(3):
                rows.append({
                    "pool_address": "Pool2",
                    "dex": "raydium",
                    "base_mint": "SOL",
                    "quote_mint": "USDC",
                    "base_reserve": 500.0,
                    "quote_reserve": 74000.0,
                    "price": 148.0,
                    "fee_bps": 30,
                    "slot": 280000000 + i,
                    "timestamp": datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
                })
            pl.DataFrame(rows).write_parquet(extra_path)

            runner = BacktestRunner()
            # Pass bare filename — should be resolved via primary's parent dir
            await runner.run(
                data_path=primary,
                config={
                    "min_spread_bps": 15.0,
                    "extra_data_files": ["second.parquet"],
                },
            )
            status = runner.status()
            assert status["state"] == "completed"
