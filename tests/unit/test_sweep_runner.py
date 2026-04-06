"""Tests for SweepRunner (Phase 4 — parameter sweep + walk-forward)."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest

from mev_kit.ui.sweep_runner import SweepRunner


def _create_merged_test_data(tmpdir: str, rows: int = 100) -> str:
    """Create merged-format test Parquet data."""
    path = os.path.join(tmpdir, "sweep_test.parquet")
    data = []
    base_ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
    for i in range(rows):
        ts = base_ts.replace(second=i % 60, minute=i // 60)
        dex_price = 148.0 + (i % 10) * 0.1
        cex_price = dex_price + 0.05 * (1 if i % 3 == 0 else -1)
        data.append({
            "timestamp": ts,
            "dex_price": dex_price,
            "cex_price": cex_price,
            "dex_venue": "jupiter",
            "cex_venue": "binance",
            "pair": "SOL/USDC",
            "slot": 280000000 + i,
        })
    pl.DataFrame(data).write_parquet(path)
    return path


class TestSweepRunner:

    def test_initial_state(self) -> None:
        runner = SweepRunner()
        status = runner.status()
        assert status["state"] == "idle"
        assert status["progress"] == 0
        assert status["total"] == 0

    @pytest.mark.asyncio
    async def test_sweep_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_merged_test_data(tmpdir)
            runner = SweepRunner()
            await runner.run(
                data_path=data_path,
                strategy="cex_dex_arb",
                sweep_params={
                    "min_spread_bps": [3, 5],
                    "fee_bps": [5, 10],
                },
                base_config={"position_size_sol": 0.1, "venue": "jupiter"},
            )
            status = runner.status()
            assert status["state"] == "completed"
            assert status["total"] == 4  # 2 x 2 combinations
            assert status["progress"] == 4
            assert isinstance(status["results"], list)
            assert len(status["results"]) == 4
            # Results should be sorted by sharpe_ratio descending
            sharpes = [r.get("sharpe_ratio", 0) for r in status["results"]]
            assert sharpes == sorted(sharpes, reverse=True)

    @pytest.mark.asyncio
    async def test_sweep_results_have_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_merged_test_data(tmpdir)
            runner = SweepRunner()
            await runner.run(
                data_path=data_path,
                strategy="cex_dex_arb",
                sweep_params={"min_spread_bps": [3, 10]},
                base_config={"position_size_sol": 0.1},
            )
            status = runner.status()
            for result in status["results"]:
                assert "params" in result
                assert "min_spread_bps" in result["params"]
                assert "total_trades" in result
                assert "sharpe_ratio" in result

    @pytest.mark.asyncio
    async def test_sweep_rejects_while_running(self) -> None:
        runner = SweepRunner()
        runner._state = "running"
        with pytest.raises(RuntimeError, match="already running"):
            await runner.run(
                data_path="/fake",
                strategy="cex_dex_arb",
                sweep_params={"x": [1]},
                base_config={},
            )

    @pytest.mark.asyncio
    async def test_walk_forward_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_merged_test_data(tmpdir, rows=60)
            runner = SweepRunner()
            await runner.run_walk_forward(
                data_path=data_path,
                strategy="cex_dex_arb",
                sweep_params={"min_spread_bps": [3, 10]},
                base_config={"position_size_sol": 0.1, "venue": "jupiter"},
                train_pct=0.7,
            )
            status = runner.status()
            assert status["state"] == "completed"
            assert len(status["results"]) == 1
            wf = status["results"][0]
            assert wf["type"] == "walk_forward"
            assert "in_sample" in wf
            assert "out_of_sample" in wf
            assert "best_params" in wf
            assert "overfit_warning" in wf
            assert wf["train_rows"] == 42  # 60 * 0.7
            assert wf["test_rows"] == 18   # 60 - 42

            # Verify temp files were cleaned up
            assert not os.path.exists(data_path.replace(".parquet", "_train.parquet"))
            assert not os.path.exists(data_path.replace(".parquet", "_test.parquet"))
