"""Tests for fill simulator calibration module."""

from __future__ import annotations

import pytest

from mev_kit.utils.fill_calibration import apply_calibration_to_profiles


class TestApplyCalibrationToProfiles:
    """Tests for apply_calibration_to_profiles."""

    @pytest.fixture()
    def sample_calibration(self) -> dict:
        """A realistic calibration result."""
        return {
            "date": "2026-04-01",
            "symbol": "solusdt",
            "samples": 48,
            "spread": {
                "mean_bps": 1.5,
                "median_bps": 1.2,
                "p95_bps": 3.0,
                "p99_bps": 5.0,
                "min_bps": 0.5,
                "max_bps": 8.0,
            },
            "depth": {
                "mean_bid_sol": 200.0,
                "mean_ask_sol": 180.0,
                "median_bid_sol": 190.0,
                "median_ask_sol": 170.0,
            },
        }

    def test_returns_binance_and_coinbase(self, sample_calibration: dict) -> None:
        """Output contains both binance_calibrated and coinbase_calibrated."""
        result = apply_calibration_to_profiles(sample_calibration)
        assert "binance_calibrated" in result
        assert "coinbase_calibrated" in result

    def test_binance_spread_matches_input(self, sample_calibration: dict) -> None:
        """Binance avg_spread_bps equals input mean_bps."""
        result = apply_calibration_to_profiles(sample_calibration)
        assert result["binance_calibrated"]["avg_spread_bps"] == 1.5

    def test_binance_depth_uses_average(self, sample_calibration: dict) -> None:
        """Binance book_depth_sol is average of bid and ask depth."""
        result = apply_calibration_to_profiles(sample_calibration)
        expected = (200.0 + 180.0) / 2  # 190.0
        assert result["binance_calibrated"]["book_depth_sol"] == expected

    def test_binance_depth_usd_uses_sol_price(self, sample_calibration: dict) -> None:
        """Binance book_depth_usd = avg_depth * 80 (rough SOL price)."""
        result = apply_calibration_to_profiles(sample_calibration)
        avg_depth = (200.0 + 180.0) / 2
        assert result["binance_calibrated"]["book_depth_usd"] == avg_depth * 80

    def test_coinbase_spread_is_2x_binance(self, sample_calibration: dict) -> None:
        """Coinbase spread is 2x Binance spread."""
        result = apply_calibration_to_profiles(sample_calibration)
        assert result["coinbase_calibrated"]["avg_spread_bps"] == 1.5 * 2

    def test_coinbase_depth_is_60pct_binance(self, sample_calibration: dict) -> None:
        """Coinbase depth is 60% of Binance depth."""
        result = apply_calibration_to_profiles(sample_calibration)
        binance_depth = result["binance_calibrated"]["book_depth_sol"]
        coinbase_depth = result["coinbase_calibrated"]["book_depth_sol"]
        assert coinbase_depth == pytest.approx(binance_depth * 0.6)

    def test_coinbase_depth_usd_is_60pct_binance(self, sample_calibration: dict) -> None:
        """Coinbase USD depth is 60% of Binance USD depth."""
        result = apply_calibration_to_profiles(sample_calibration)
        binance_usd = result["binance_calibrated"]["book_depth_usd"]
        coinbase_usd = result["coinbase_calibrated"]["book_depth_usd"]
        assert coinbase_usd == pytest.approx(binance_usd * 0.6)

    def test_output_structure_keys(self, sample_calibration: dict) -> None:
        """Each venue profile has all expected keys."""
        result = apply_calibration_to_profiles(sample_calibration)
        expected_keys = {"avg_spread_bps", "book_depth_usd", "book_depth_sol"}
        assert set(result["binance_calibrated"].keys()) == expected_keys
        assert set(result["coinbase_calibrated"].keys()) == expected_keys

    def test_defaults_when_missing_keys(self) -> None:
        """Uses defaults when calibration dict is empty."""
        result = apply_calibration_to_profiles({})
        assert result["binance_calibrated"]["avg_spread_bps"] == 1.0
        assert result["binance_calibrated"]["book_depth_sol"] == 100.0
        assert result["coinbase_calibrated"]["avg_spread_bps"] == 2.0
        assert result["coinbase_calibrated"]["book_depth_sol"] == pytest.approx(60.0)
