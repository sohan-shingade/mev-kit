"""Integer arithmetic for financial calculations.

All money values are stored and computed as integers (lamports, micro-USDC,
basis points) to avoid floating-point precision errors. Conversion to float
happens ONLY at the display boundary.

Units:
    SOL:      1 SOL = 1_000_000_000 lamports
    USDC:     1 USDC = 1_000_000 micro-USDC
    Basis pt: 1 bps = 0.01% = 0.0001
    Price:    stored as micro-USD per SOL (6 decimal places)

Usage:
    from mev_kit.utils.precision import (
        sol_to_lamports, lamports_to_sol,
        spread_bps_int, profit_lamports,
        bps_to_fraction_e6, mul_bps,
    )

    # Calculate spread in integer basis points
    spread = spread_bps_int(cex_price_usd=148.50, dex_price_usd=147.80)
    # Returns: 47  (47 basis points)

    # Calculate profit in lamports
    profit = profit_lamports(spread_bps=47, fee_bps=25, size_lamports=1_000_000_000)
    # Returns: 2_200_000  (0.0022 SOL)
"""

from __future__ import annotations

# ── Constants ──

LAMPORTS_PER_SOL: int = 1_000_000_000
MICRO_PER_USDC: int = 1_000_000
PRICE_SCALE: int = 1_000_000  # 6 decimal places for price

# ── Conversion ──


def sol_to_lamports(sol: float) -> int:
    """Convert SOL (float) to lamports (int). Use at input boundaries only."""
    return int(sol * LAMPORTS_PER_SOL + 0.5)  # Round half-up


def lamports_to_sol(lamports: int) -> float:
    """Convert lamports (int) to SOL (float). Use at display boundaries only."""
    return lamports / LAMPORTS_PER_SOL


def price_to_scaled(price: float) -> int:
    """Convert a price (float) to a scaled integer (6 decimal places)."""
    return int(price * PRICE_SCALE + 0.5)


def scaled_to_price(scaled: int) -> float:
    """Convert a scaled price integer back to float for display."""
    return scaled / PRICE_SCALE


# ── Spread calculation (integer) ──


def spread_bps_int(cex_price_usd: float, dex_price_usd: float) -> int:
    """Calculate spread in integer basis points using scaled integer math.

    spread_bps = |cex - dex| / cex × 10000

    Uses 6-decimal scaled integers to avoid float division:
        spread = |cex_scaled - dex_scaled| × 10000 / cex_scaled

    Returns:
        Integer basis points (e.g., 47 means 47 bps = 0.47%)
    """
    cex_s = price_to_scaled(cex_price_usd)
    dex_s = price_to_scaled(dex_price_usd)

    if cex_s == 0:
        return 0

    # Integer division: |diff| * 10000 / cex
    diff = abs(cex_s - dex_s)
    return (diff * 10_000 + cex_s // 2) // cex_s  # Rounded integer division


def net_spread_bps(gross_bps: int, fee_bps: int) -> int:
    """Subtract fee from gross spread. Returns integer bps."""
    return gross_bps - fee_bps


# ── Profit calculation (integer lamports) ──


def profit_lamports(
    spread_bps: int,
    fee_bps: int,
    size_lamports: int,
    tip_bps: int = 0,
    slippage_bps: int = 0,
) -> int:
    """Calculate net profit in lamports using pure integer arithmetic.

    net_profit = size × (spread - fee - tip - slippage) / 10000

    All inputs are integers. Output is integer lamports.
    """
    net_bps = spread_bps - fee_bps - tip_bps - slippage_bps
    if net_bps <= 0:
        return 0

    # Integer multiplication then division — no float anywhere
    return (size_lamports * net_bps) // 10_000


def mul_bps(amount_lamports: int, bps: int) -> int:
    """Multiply an amount by a basis point fraction.

    result = amount × bps / 10000

    Example: mul_bps(1_000_000_000, 25) = 2_500_000  (0.25% of 1 SOL)
    """
    return (amount_lamports * bps) // 10_000


def div_ceil(a: int, b: int) -> int:
    """Integer ceiling division: ceil(a / b)."""
    return (a + b - 1) // b


# ── Fee calculation (Raydium exact) ──


def raydium_fee(amount_lamports: int, fee_num: int = 25, fee_den: int = 10_000) -> int:
    """Calculate Raydium fee using ceiling division (exact match to on-chain).

    fee = ceil(amount × fee_numerator / fee_denominator)

    This matches the Raydium AMM v4 source code in math.rs.
    """
    return div_ceil(amount_lamports * fee_num, fee_den)


def raydium_swap_output(
    amount_in_lamports: int,
    reserve_in_lamports: int,
    reserve_out_lamports: int,
    fee_num: int = 25,
    fee_den: int = 10_000,
) -> int:
    """Calculate Raydium AMM swap output using exact integer math.

    Matches the on-chain constant product formula:
        fee = ceil(amount_in × fee_num / fee_den)
        amount_in_net = amount_in - fee
        amount_out = reserve_out × amount_in_net / (reserve_in + amount_in_net)

    All arithmetic is integer — no float anywhere.
    """
    fee = raydium_fee(amount_in_lamports, fee_num, fee_den)
    amount_in_net = amount_in_lamports - fee

    if reserve_in_lamports == 0 or reserve_out_lamports == 0:
        return 0

    # Constant product: amount_out = R_out × in_net / (R_in + in_net)
    numerator = reserve_out_lamports * amount_in_net
    denominator = reserve_in_lamports + amount_in_net

    return numerator // denominator


def price_impact_bps_int(
    trade_size_lamports: int,
    reserve_lamports: int,
) -> int:
    """Price impact in integer basis points for constant product AMM.

    impact = trade_size / (reserve + trade_size) × 10000

    Pure integer arithmetic.
    """
    if reserve_lamports == 0:
        return 10_000  # 100% impact

    denominator = reserve_lamports + trade_size_lamports
    return (trade_size_lamports * 10_000) // denominator


# ── Aggregation (integer accumulation) ──


class ProfitAccumulator:
    """Accumulate profit/loss in integer lamports to avoid float drift.

    Usage:
        acc = ProfitAccumulator()
        acc.add(profit_lamports=2_500_000)  # +0.0025 SOL
        acc.add(profit_lamports=-1_000_000) # -0.001 SOL
        print(acc.total_sol)  # 0.0015 (exact)
    """

    def __init__(self) -> None:
        self._total_lamports: int = 0
        self._count: int = 0
        self._wins: int = 0
        self._best_lamports: int = 0
        self._worst_lamports: int = 0

    def add(self, profit_lamports: int) -> None:
        self._total_lamports += profit_lamports
        self._count += 1
        if profit_lamports > 0:
            self._wins += 1
        if profit_lamports > self._best_lamports:
            self._best_lamports = profit_lamports
        if self._count == 1 or profit_lamports < self._worst_lamports:
            self._worst_lamports = profit_lamports

    @property
    def total_lamports(self) -> int:
        return self._total_lamports

    @property
    def total_sol(self) -> float:
        """For display only."""
        return lamports_to_sol(self._total_lamports)

    @property
    def count(self) -> int:
        return self._count

    @property
    def win_rate(self) -> float:
        """For display only."""
        if self._count == 0:
            return 0.0
        return self._wins / self._count

    @property
    def avg_sol(self) -> float:
        """For display only."""
        if self._count == 0:
            return 0.0
        return lamports_to_sol(self._total_lamports // self._count)

    @property
    def best_sol(self) -> float:
        return lamports_to_sol(self._best_lamports)

    @property
    def worst_sol(self) -> float:
        return lamports_to_sol(self._worst_lamports)
