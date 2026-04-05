"""Tests for backtest data preparation and merged replay adapter."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mev_kit.ui.data_prep import prepare_backtest_data


def _make_dex_data(tmpdir: str, n: int = 10, start_offset: int = 0) -> str:
    """Create synthetic DEX (Birdeye-format) Parquet data."""
    base_ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append({
            "pool_address": "birdeye_aggregated",
            "dex": "raydium",
            "base_mint": "So11111111111111111111111111111111111111112",
            "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "base_reserve": 0.0,
            "quote_reserve": 0.0,
            "price": 150.0 + i * 0.5,
            "fee_bps": 30,
            "slot": 0,
            "timestamp": base_ts + timedelta(minutes=i + start_offset),
        })
    path = os.path.join(tmpdir, "dex.parquet")
    pl.DataFrame(rows).write_parquet(path)
    return path


def _make_cex_data(tmpdir: str, n: int = 10, start_offset: int = 0) -> str:
    """Create synthetic CEX (Binance-format) Parquet data."""
    base_ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(n):
        rows.append({
            "symbol": "SOLUSDT",
            "price": 150.2 + i * 0.5,
            "volume": 1000.0,
            "timestamp": base_ts + timedelta(minutes=i + start_offset),
            "open": 150.0 + i * 0.5,
            "high": 150.5 + i * 0.5,
            "low": 149.5 + i * 0.5,
            "close": 150.2 + i * 0.5,
        })
    path = os.path.join(tmpdir, "cex.parquet")
    pl.DataFrame(rows).write_parquet(path)
    return path


class TestPrepareBacktestData:
    """Tests for the prepare_backtest_data function."""

    def test_merge_produces_correct_row_count(self) -> None:
        """Inner join on overlapping timestamps gives expected rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=10)
            cex_path = _make_cex_data(tmpdir, n=10)
            output_path = os.path.join(tmpdir, "merged.parquet")

            stats = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            assert stats["rows"] == 10
            assert os.path.exists(output_path)

    def test_lag_shifts_prices_by_one(self) -> None:
        """With lag=True, first row is dropped and prices shift by 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=10)
            cex_path = _make_cex_data(tmpdir, n=10)
            output_path = os.path.join(tmpdir, "merged.parquet")

            stats_no_lag = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            stats_lag = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=True,
            )

            # Lagged should have one fewer row
            assert stats_lag["rows"] == stats_no_lag["rows"] - 1
            assert stats_lag["lag_applied"] is True
            assert stats_no_lag["lag_applied"] is False

    def test_lag_values_are_shifted(self) -> None:
        """Verify that lagged output actually contains the previous row's prices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=5)
            cex_path = _make_cex_data(tmpdir, n=5)

            # First without lag to get the raw values
            raw_path = os.path.join(tmpdir, "raw.parquet")
            prepare_backtest_data(
                dex_path=dex_path, cex_path=cex_path,
                output_path=raw_path, interval_seconds=60, lag=False,
            )
            raw_df = pl.read_parquet(raw_path)

            # Then with lag
            lag_path = os.path.join(tmpdir, "lag.parquet")
            prepare_backtest_data(
                dex_path=dex_path, cex_path=cex_path,
                output_path=lag_path, interval_seconds=60, lag=True,
            )
            lag_df = pl.read_parquet(lag_path)

            # The lagged dex_price at row 0 should equal raw dex_price at row 0
            # (because lag shifts by 1 then drops nulls, so lagged row 0 = raw row 0's price at raw row 1's timestamp)
            assert float(lag_df["dex_price"][0]) == float(raw_df["dex_price"][0])
            assert float(lag_df["cex_price"][0]) == float(raw_df["cex_price"][0])

    def test_spread_calculation(self) -> None:
        """Verify spread_bps is computed correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=5)
            cex_path = _make_cex_data(tmpdir, n=5)
            output_path = os.path.join(tmpdir, "merged.parquet")

            stats = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            # avg_spread should be a positive number
            assert stats["avg_spread_bps"] > 0
            assert stats["max_spread_bps"] >= stats["avg_spread_bps"]

            # Verify from the actual output
            df = pl.read_parquet(output_path)
            # Manual check: spread_bps = abs(cex - dex) / cex * 10000
            row0_dex = float(df["dex_price"][0])
            row0_cex = float(df["cex_price"][0])
            expected_spread = abs(row0_cex - row0_dex) / row0_cex * 10000
            actual_spread = float(df["spread_bps"][0])
            assert abs(actual_spread - expected_spread) < 0.01

    def test_non_overlapping_data_returns_error(self) -> None:
        """When DEX and CEX have no overlapping timestamps, return error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # DEX starts at minute 0, CEX starts at minute 100 (no overlap)
            dex_path = _make_dex_data(tmpdir, n=5, start_offset=0)
            cex_path = _make_cex_data(tmpdir, n=5, start_offset=100)
            output_path = os.path.join(tmpdir, "merged.parquet")

            stats = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            assert stats["rows"] == 0
            assert "error" in stats

    def test_output_has_required_columns(self) -> None:
        """Merged Parquet must have all columns the pipeline needs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=5)
            cex_path = _make_cex_data(tmpdir, n=5)
            output_path = os.path.join(tmpdir, "merged.parquet")

            prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            df = pl.read_parquet(output_path)
            required = {
                "timestamp", "dex_price", "cex_price", "spread_bps",
                "pool_address", "dex", "base_mint", "quote_mint",
                "base_reserve", "quote_reserve", "price", "fee_bps",
                "slot", "symbol", "cex_close",
            }
            assert required.issubset(set(df.columns))

    def test_partial_overlap(self) -> None:
        """When datasets partially overlap, only the overlap is included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # DEX: minutes 0-9, CEX: minutes 5-14 → overlap = minutes 5-9 = 5 rows
            dex_path = _make_dex_data(tmpdir, n=10, start_offset=0)
            cex_path = _make_cex_data(tmpdir, n=10, start_offset=5)
            output_path = os.path.join(tmpdir, "merged.parquet")

            stats = prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            assert stats["rows"] == 5


class TestMergedReplayAdapter:
    """Tests for the MergedReplayAdapter."""

    @pytest.mark.asyncio
    async def test_emits_paired_updates(self) -> None:
        """Each row should produce exactly two StateUpdates: DEX then CEX."""
        from mev_kit.adapters.ingest.merged_replay import MergedReplayAdapter
        from mev_kit.models import Source

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create merged data
            dex_path = _make_dex_data(tmpdir, n=5)
            cex_path = _make_cex_data(tmpdir, n=5)
            output_path = os.path.join(tmpdir, "merged.parquet")

            prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            adapter = MergedReplayAdapter({"path": output_path})
            await adapter.connect()
            adapter._running = True

            updates = []
            async for update in adapter.stream():
                updates.append(update)

            await adapter.disconnect()

            # 5 rows should produce 10 updates (2 per row)
            assert len(updates) == 10

            # Odd indices (0, 2, 4, ...) should be DEX (PARQUET_REPLAY)
            # Even indices (1, 3, 5, ...) should be CEX (BINANCE_WS)
            for i in range(0, len(updates), 2):
                assert updates[i].source == Source.PARQUET_REPLAY
                assert updates[i].pool is not None
                assert updates[i + 1].source == Source.BINANCE_WS
                assert updates[i + 1].price is not None

    @pytest.mark.asyncio
    async def test_dex_and_cex_prices_match(self) -> None:
        """DEX and CEX updates from the same row have consistent prices."""
        from mev_kit.adapters.ingest.merged_replay import MergedReplayAdapter

        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=3)
            cex_path = _make_cex_data(tmpdir, n=3)
            output_path = os.path.join(tmpdir, "merged.parquet")

            prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            adapter = MergedReplayAdapter({"path": output_path})
            await adapter.connect()
            adapter._running = True

            updates = []
            async for update in adapter.stream():
                updates.append(update)

            await adapter.disconnect()

            # For each pair, the DEX pool price should match dex_price in the file
            merged_df = pl.read_parquet(output_path)
            for i, row_idx in enumerate(range(0, len(updates), 2)):
                dex_update = updates[row_idx]
                cex_update = updates[row_idx + 1]
                assert dex_update.pool is not None
                assert cex_update.price is not None
                assert dex_update.pool.price == float(merged_df["dex_price"][i])
                assert cex_update.price.price == float(merged_df["cex_price"][i])


class TestDetectSourceType:
    """Tests for merged data type detection in the backtest runner."""

    def test_detects_merged_type(self) -> None:
        """detect_source_type should return 'merged' for merged data."""
        from mev_kit.ui.backtest_runner import detect_source_type

        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=3)
            cex_path = _make_cex_data(tmpdir, n=3)
            output_path = os.path.join(tmpdir, "merged.parquet")

            prepare_backtest_data(
                dex_path=dex_path,
                cex_path=cex_path,
                output_path=output_path,
                interval_seconds=60,
                lag=False,
            )

            assert detect_source_type(output_path) == "merged"

    def test_non_merged_is_not_merged(self) -> None:
        """Regular pool data should not be detected as merged."""
        from mev_kit.ui.backtest_runner import detect_source_type

        with tempfile.TemporaryDirectory() as tmpdir:
            dex_path = _make_dex_data(tmpdir, n=3)
            assert detect_source_type(dex_path) == "pool"
