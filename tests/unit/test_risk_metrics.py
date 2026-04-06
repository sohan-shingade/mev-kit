"""Tests for risk_metrics utility functions."""

from __future__ import annotations

import pytest

from mev_kit.utils.risk_metrics import (
    compute_equity_curve,
    compute_hourly_breakdown,
    compute_risk_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(pnl: float, ts: str = "2025-01-01T12:00:00Z") -> dict:
    """Build a minimal trade dict with the given P&L."""
    return {"simulated_profit_sol": pnl, "detected_at": ts}


# ---------------------------------------------------------------------------
# compute_risk_metrics
# ---------------------------------------------------------------------------

class TestComputeRiskMetrics:
    """Tests for compute_risk_metrics."""

    def test_known_pnl_sequence(self):
        """Verify Sharpe, drawdown, and profit factor on a known sequence."""
        trades = [_trade(0.01), _trade(-0.005), _trade(0.02), _trade(-0.003), _trade(0.015)]
        m = compute_risk_metrics(trades)

        assert m["sharpe_ratio"] > 0, "Sharpe should be positive for net-positive trades"
        assert m["max_drawdown_sol"] > 0, "Max drawdown should be positive"
        assert m["profit_factor"] > 1.0, "Profit factor should exceed 1 for net-positive"
        assert m["avg_win_sol"] > 0, "Average win should be positive"
        assert m["avg_loss_sol"] < 0, "Average loss should be negative"
        assert m["max_win_streak"] >= 1
        assert m["max_loss_streak"] >= 1
        assert m["gross_profit_sol"] == pytest.approx(0.045, abs=1e-6)
        assert m["gross_loss_sol"] == pytest.approx(0.008, abs=1e-6)

    def test_all_wins(self):
        """All-win sequence: profit_factor capped, Sharpe positive."""
        trades = [_trade(0.01) for _ in range(10)]
        m = compute_risk_metrics(trades)

        assert m["sharpe_ratio"] > 0
        assert m["profit_factor"] == 999, "Profit factor should be capped at 999 when no losses"
        assert m["max_drawdown_sol"] == 0
        assert m["max_loss_streak"] == 0
        assert m["max_win_streak"] == 10

    def test_all_losses(self):
        """All-loss sequence: negative Sharpe, max drawdown = total loss."""
        trades = [_trade(-0.01) for _ in range(5)]
        m = compute_risk_metrics(trades)

        assert m["sharpe_ratio"] < 0, "Sharpe should be negative for all-loss trades"
        assert m["max_drawdown_sol"] == pytest.approx(0.05, abs=1e-6)
        assert m["profit_factor"] == 0
        assert m["max_win_streak"] == 0
        assert m["max_loss_streak"] == 5

    def test_empty_trades(self):
        """Empty input returns zeroed-out metrics."""
        m = compute_risk_metrics([])

        assert m["sharpe_ratio"] == 0
        assert m["sortino_ratio"] == 0
        assert m["calmar_ratio"] == 0
        assert m["profit_factor"] == 0
        assert m["max_drawdown_sol"] == 0
        assert m["avg_win_sol"] == 0
        assert m["avg_loss_sol"] == 0

    def test_single_trade_no_division_by_zero(self):
        """A single trade should return empty metrics (need >= 2 for variance)."""
        m = compute_risk_metrics([_trade(0.01)])

        # With only 1 trade we can't compute variance, so we get zeroed metrics
        assert m["sharpe_ratio"] == 0
        assert m["sortino_ratio"] == 0

    def test_sortino_positive_no_downside(self):
        """If there's no downside, sortino should be capped at 999."""
        trades = [_trade(0.01), _trade(0.02), _trade(0.005)]
        m = compute_risk_metrics(trades)

        assert m["sortino_ratio"] == 999

    def test_calmar_with_drawdown(self):
        """Calmar = total_return / max_drawdown."""
        # Sequence: +0.1, -0.05, +0.02 => total=0.07, max_dd=0.05
        trades = [_trade(0.1), _trade(-0.05), _trade(0.02)]
        m = compute_risk_metrics(trades)

        assert m["calmar_ratio"] == pytest.approx(0.07 / 0.05, abs=0.1)


# ---------------------------------------------------------------------------
# compute_equity_curve
# ---------------------------------------------------------------------------

class TestComputeEquityCurve:
    """Tests for compute_equity_curve."""

    def test_cumulative_pnl_correct(self):
        """Cumulative P&L should be running sum."""
        trades = [_trade(0.01), _trade(0.02), _trade(-0.005)]
        curve = compute_equity_curve(trades)

        assert len(curve) == 3
        assert curve[0]["pnl"] == pytest.approx(0.01, abs=1e-8)
        assert curve[1]["pnl"] == pytest.approx(0.03, abs=1e-8)
        assert curve[2]["pnl"] == pytest.approx(0.025, abs=1e-8)

    def test_drawdown_tracks_correctly(self):
        """Drawdown should be negative when below high water mark."""
        trades = [_trade(0.05), _trade(-0.02), _trade(-0.01)]
        curve = compute_equity_curve(trades)

        assert curve[0]["drawdown"] == 0  # at high water
        assert curve[1]["drawdown"] == pytest.approx(-0.02, abs=1e-8)
        assert curve[2]["drawdown"] == pytest.approx(-0.03, abs=1e-8)

    def test_high_water_only_goes_up(self):
        """High water mark should be monotonically non-decreasing."""
        trades = [_trade(0.01), _trade(-0.005), _trade(0.02), _trade(-0.001)]
        curve = compute_equity_curve(trades)

        highs = [p["high_water"] for p in curve]
        for i in range(1, len(highs)):
            assert highs[i] >= highs[i - 1], f"High water decreased at index {i}"

    def test_timestamps_preserved(self):
        """Timestamps from trades should flow through."""
        trades = [
            _trade(0.01, "2025-01-01T10:00:00Z"),
            _trade(0.02, "2025-01-01T11:00:00Z"),
        ]
        curve = compute_equity_curve(trades)

        assert curve[0]["timestamp"] == "2025-01-01T10:00:00Z"
        assert curve[1]["timestamp"] == "2025-01-01T11:00:00Z"

    def test_empty_trades(self):
        """Empty input returns empty curve."""
        assert compute_equity_curve([]) == []

    def test_uses_estimated_profit_fallback(self):
        """Falls back to estimated_profit_sol when simulated is missing."""
        trade = {"estimated_profit_sol": 0.05, "detected_at": "2025-01-01T00:00:00Z"}
        curve = compute_equity_curve([trade])

        assert curve[0]["pnl"] == pytest.approx(0.05, abs=1e-8)


# ---------------------------------------------------------------------------
# compute_hourly_breakdown
# ---------------------------------------------------------------------------

class TestComputeHourlyBreakdown:
    """Tests for compute_hourly_breakdown."""

    def test_returns_24_entries(self):
        """Should always return exactly 24 hourly buckets."""
        breakdown = compute_hourly_breakdown([])
        assert len(breakdown) == 24

    def test_trade_counts_sum_correctly(self):
        """Total trade counts across hours should match input length."""
        trades = [
            _trade(0.01, "2025-01-01T10:30:00Z"),
            _trade(0.02, "2025-01-01T10:45:00Z"),
            _trade(-0.01, "2025-01-01T14:00:00Z"),
        ]
        breakdown = compute_hourly_breakdown(trades)
        total = sum(h["trade_count"] for h in breakdown)

        assert total == 3

    def test_pnl_by_hour(self):
        """P&L should be correctly bucketed by hour."""
        trades = [
            _trade(0.01, "2025-01-01T10:00:00Z"),
            _trade(0.02, "2025-01-01T10:30:00Z"),
            _trade(-0.005, "2025-01-01T14:00:00Z"),
        ]
        breakdown = compute_hourly_breakdown(trades)
        hour_10 = next(h for h in breakdown if h["hour"] == 10)
        hour_14 = next(h for h in breakdown if h["hour"] == 14)

        assert hour_10["trade_count"] == 2
        assert hour_10["total_pnl"] == pytest.approx(0.03, abs=1e-6)
        assert hour_10["win_rate"] == pytest.approx(1.0, abs=1e-3)
        assert hour_14["trade_count"] == 1
        assert hour_14["total_pnl"] == pytest.approx(-0.005, abs=1e-6)
        assert hour_14["win_rate"] == pytest.approx(0.0, abs=1e-3)

    def test_hours_are_sorted(self):
        """Hours should be in order 0-23."""
        breakdown = compute_hourly_breakdown([_trade(0.01, "2025-01-01T23:00:00Z")])
        hours = [h["hour"] for h in breakdown]
        assert hours == list(range(24))

    def test_win_rate_zero_for_empty_hours(self):
        """Hours with no trades should have win_rate=0."""
        breakdown = compute_hourly_breakdown([_trade(0.01, "2025-01-01T05:00:00Z")])
        hour_0 = next(h for h in breakdown if h["hour"] == 0)

        assert hour_0["trade_count"] == 0
        assert hour_0["win_rate"] == 0
