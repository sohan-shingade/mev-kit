"""Tests for BacktestRunner."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest

from mev_kit.ui.backtest_runner import BacktestRunner


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
