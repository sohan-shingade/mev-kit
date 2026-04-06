"""Tests for integer arithmetic precision module."""

from __future__ import annotations

from mev_kit.utils.precision import (
    ProfitAccumulator,
    div_ceil,
    lamports_to_sol,
    mul_bps,
    price_impact_bps_int,
    profit_lamports,
    raydium_fee,
    raydium_swap_output,
    sol_to_lamports,
    spread_bps_int,
)


class TestConversions:
    def test_sol_to_lamports(self) -> None:
        assert sol_to_lamports(1.0) == 1_000_000_000
        assert sol_to_lamports(0.001) == 1_000_000
        assert sol_to_lamports(0.0) == 0

    def test_lamports_to_sol(self) -> None:
        assert lamports_to_sol(1_000_000_000) == 1.0
        assert lamports_to_sol(1_000_000) == 0.001
        assert lamports_to_sol(0) == 0.0

    def test_roundtrip(self) -> None:
        for sol in [0.01, 0.1, 1.0, 100.0, 0.000001]:
            assert abs(lamports_to_sol(sol_to_lamports(sol)) - sol) < 1e-9


class TestSpreadBps:
    def test_equal_prices(self) -> None:
        assert spread_bps_int(100.0, 100.0) == 0

    def test_1_percent_spread(self) -> None:
        # 1% = 100 bps
        assert spread_bps_int(100.0, 99.0) == 100

    def test_small_spread(self) -> None:
        # 10 bps = 0.1%
        result = spread_bps_int(148.50, 148.3515)
        assert result == 10

    def test_symmetry(self) -> None:
        # |cex - dex| / cex — direction doesn't matter for magnitude
        a = spread_bps_int(100.0, 99.0)
        b = spread_bps_int(100.0, 101.0)
        assert a == b

    def test_zero_cex(self) -> None:
        assert spread_bps_int(0.0, 100.0) == 0


class TestProfitLamports:
    def test_basic_profit(self) -> None:
        # 50 bps spread, 25 bps fee, 1 SOL = 25 bps net = 0.0025 SOL
        result = profit_lamports(
            spread_bps=50, fee_bps=25, size_lamports=1_000_000_000
        )
        assert result == 2_500_000  # 0.0025 SOL

    def test_unprofitable(self) -> None:
        result = profit_lamports(
            spread_bps=20, fee_bps=25, size_lamports=1_000_000_000
        )
        assert result == 0

    def test_with_tip_and_slippage(self) -> None:
        result = profit_lamports(
            spread_bps=100, fee_bps=25, tip_bps=10, slippage_bps=5,
            size_lamports=1_000_000_000,
        )
        # 100 - 25 - 10 - 5 = 60 bps net = 0.006 SOL
        assert result == 6_000_000

    def test_exact_zero(self) -> None:
        result = profit_lamports(
            spread_bps=25, fee_bps=25, size_lamports=1_000_000_000
        )
        assert result == 0


class TestMulBps:
    def test_25_bps(self) -> None:
        # 0.25% of 1 SOL = 0.0025 SOL = 2,500,000 lamports
        assert mul_bps(1_000_000_000, 25) == 2_500_000

    def test_100_bps(self) -> None:
        # 1% of 1 SOL = 0.01 SOL
        assert mul_bps(1_000_000_000, 100) == 10_000_000

    def test_zero(self) -> None:
        assert mul_bps(1_000_000_000, 0) == 0


class TestRaydiumFee:
    def test_exact_raydium_fee(self) -> None:
        # ceil(1_000_000_000 × 25 / 10000) = ceil(2_500_000) = 2_500_000
        assert raydium_fee(1_000_000_000) == 2_500_000

    def test_ceiling_division(self) -> None:
        # ceil(100 × 25 / 10000) = ceil(0.25) = 1
        assert raydium_fee(100) == 1

    def test_small_amount(self) -> None:
        # ceil(1 × 25 / 10000) = ceil(0.0025) = 1
        assert raydium_fee(1) == 1


class TestRaydiumSwapOutput:
    def test_basic_swap(self) -> None:
        # 1 SOL into a pool with 50K SOL and 7.4M USDC (price ~148)
        output = raydium_swap_output(
            amount_in_lamports=1_000_000_000,
            reserve_in_lamports=50_000_000_000_000,  # 50K SOL
            reserve_out_lamports=7_400_000_000_000,   # 7.4M USDC (micro)
        )
        # After 0.25% fee: 997,500,000 lamports net input
        # Output ≈ 7.4M × 997.5M / (50T + 997.5M) ≈ ~147,970 micro-USDC
        assert output > 0
        assert output < 7_400_000_000_000  # Less than full reserve

    def test_zero_reserve(self) -> None:
        assert raydium_swap_output(1_000_000, 0, 1_000_000) == 0


class TestPriceImpact:
    def test_small_trade(self) -> None:
        # 1 SOL into 50K SOL pool = ~0.2 bps
        impact = price_impact_bps_int(
            trade_size_lamports=1_000_000_000,
            reserve_lamports=50_000_000_000_000,
        )
        assert impact == 0  # Rounds to 0 (actually 0.02 bps)

    def test_large_trade(self) -> None:
        # 1000 SOL into 50K SOL pool = ~196 bps
        impact = price_impact_bps_int(
            trade_size_lamports=1_000_000_000_000,
            reserve_lamports=50_000_000_000_000,
        )
        assert 190 <= impact <= 200

    def test_zero_reserve(self) -> None:
        assert price_impact_bps_int(1_000_000, 0) == 10_000


class TestDivCeil:
    def test_exact(self) -> None:
        assert div_ceil(10, 5) == 2

    def test_round_up(self) -> None:
        assert div_ceil(11, 5) == 3
        assert div_ceil(1, 3) == 1


class TestProfitAccumulator:
    def test_accumulation_no_drift(self) -> None:
        """10,000 small profits should sum exactly."""
        acc = ProfitAccumulator()
        for _ in range(10_000):
            acc.add(100_000)  # 0.0001 SOL each
        assert acc.total_lamports == 1_000_000_000  # Exactly 1 SOL
        assert acc.total_sol == 1.0

    def test_win_rate(self) -> None:
        acc = ProfitAccumulator()
        acc.add(100_000)
        acc.add(-50_000)
        acc.add(200_000)
        assert acc.count == 3
        assert abs(acc.win_rate - 2 / 3) < 1e-10

    def test_best_worst(self) -> None:
        acc = ProfitAccumulator()
        acc.add(500_000)
        acc.add(-200_000)
        acc.add(1_000_000)
        assert acc.best_sol == 0.001
        assert acc.worst_sol == -0.0002
