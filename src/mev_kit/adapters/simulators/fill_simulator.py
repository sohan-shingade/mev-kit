"""Realistic fill simulator — models venue-specific execution.

For each detected opportunity, simulates what would actually happen
on-chain. Based on exact protocol mechanics:

- Raydium AMM v4: constant product x*y=k, fee deducted before swap
  Formula: amount_out = (R_out × amount_in_net) / (R_in + amount_in_net)
  Fee: ceil(amount_in × 25 / 10000) = 0.25%
  Source: raydium-amm/program/src/math.rs

- Orca Whirlpools: concentrated liquidity (Uni V3 style)
  Slippage depends on tick-level liquidity distribution
  Approximated as constant product with capital_efficiency multiplier
  Fee: 0.30% for standard SOL/USDC (tick spacing 64)
  Source: whirlpools/programs/whirlpool/src/math/swap_math.rs

- Jupiter: routes across multiple venues, splits trades
  Zero Jupiter fee — only underlying venue fees apply
  Models route splitting as reduced price impact
  Source: dev.jup.ag/docs/swap/routing

- Jito bundles: auctions every 200ms, landing rate depends on
  tip/CU efficiency vs competing searchers
  Source: jito-foundation.gitbook.io
"""

from __future__ import annotations

import math
import random
from typing import Any

import polars as pl
import structlog

from mev_kit.adapters.simulators.base import Simulator
from mev_kit.models import Opportunity, SimulationResult

logger = structlog.get_logger()

LAMPORTS_PER_SOL = 1_000_000_000

# Estimated pool depths (SOL reserves) for major pairs
# Used when actual reserves aren't available in backtest data
# Based on typical Raydium/Orca SOL/USDC pool sizes
DEFAULT_POOL_DEPTH_SOL = {
    "raydium": 50_000,    # ~$4M TVL one side
    "orca": 30_000,       # ~$2.5M TVL one side
    "jupiter": 80_000,    # Aggregated across venues
    "aggregated": 60_000, # Weighted average
    "binance": 500_000,   # Deep order book — $40M+ depth
    "coinbase": 200_000,  # Shallower than Binance for SOL
}

VENUE_PROFILES: dict[str, dict[str, Any]] = {
    "raydium": {
        "label": "Raydium AMM v4",
        "fee_numerator": 25,
        "fee_denominator": 10_000,     # 0.25% — exact from state.rs
        "slippage_model": "constant_product",
        "capital_efficiency": 1.0,     # Standard AMM, no concentration
        "landing_rate_base": 0.40,     # Moderately competitive
        "landing_rate_uncompetitive": 0.95,  # No competition
        "avg_latency_slots": 5,        # 4-6 slots from Jito benchmark
        "slot_time_ms": 400,
        "tip_pct_of_profit": 0.10,     # 10% of net profit as tip
        "min_tip_lamports": 10_000,
        "compute_units": 200_000,      # Typical Raydium swap CU
    },
    "orca": {
        "label": "Orca Whirlpool",
        "fee_numerator": 30,
        "fee_denominator": 10_000,     # 0.30% for tick spacing 64
        "slippage_model": "concentrated_liquidity",
        "capital_efficiency": 3.0,     # ~3x vs constant product (conservative estimate)
        "landing_rate_base": 0.40,
        "landing_rate_uncompetitive": 0.95,
        "avg_latency_slots": 5,
        "slot_time_ms": 400,
        "tip_pct_of_profit": 0.10,
        "min_tip_lamports": 10_000,
        "compute_units": 300_000,      # CLMM swaps use more CU
    },
    "jupiter": {
        "label": "Jupiter Aggregated",
        "fee_numerator": 0,            # Jupiter charges ZERO fee
        "fee_denominator": 10_000,     # Underlying venue fees still apply
        "underlying_fee_bps": 25,      # Weighted avg of venue fees hit
        "slippage_model": "aggregated",
        "capital_efficiency": 4.0,     # Route splitting across venues
        "landing_rate_base": 0.45,     # Slightly better routing
        "landing_rate_uncompetitive": 0.95,
        "avg_latency_slots": 6,        # +1 slot for routing computation
        "slot_time_ms": 400,
        "tip_pct_of_profit": 0.08,     # Tighter tips, better routing
        "min_tip_lamports": 10_000,
        "compute_units": 400_000,      # Multi-hop uses more CU
    },
    "aggregated": {
        "label": "DEX Aggregated (estimate)",
        "fee_numerator": 25,
        "fee_denominator": 10_000,     # 0.25% average
        "slippage_model": "constant_product",
        "capital_efficiency": 2.0,     # Between AMM and CLMM
        "landing_rate_base": 0.40,
        "landing_rate_uncompetitive": 0.95,
        "avg_latency_slots": 5,
        "slot_time_ms": 400,
        "tip_pct_of_profit": 0.10,
        "min_tip_lamports": 10_000,
        "compute_units": 250_000,
    },
    # ── CEX venues — order book model, not AMM ──
    "binance": {
        "label": "Binance",
        "fee_numerator": 10,
        "fee_denominator": 10_000,     # 0.10% maker/taker (VIP0 spot)
        "slippage_model": "order_book",
        "capital_efficiency": 10.0,    # Deep book, very low impact for small sizes
        "landing_rate_base": 0.98,     # CEX orders almost always fill
        "landing_rate_uncompetitive": 0.99,
        "avg_latency_slots": 0,        # No Solana slots — CEX latency below
        "slot_time_ms": 50,            # ~50ms API round-trip
        "tip_pct_of_profit": 0.0,      # No Jito tips on CEX
        "min_tip_lamports": 0,
        "compute_units": 0,            # Not a Solana tx
        # CEX-specific params
        "maker_fee_bps": 10,           # 0.10% maker (VIP0)
        "taker_fee_bps": 10,           # 0.10% taker (VIP0)
        "book_depth_usd": 5_000_000,   # Typical bid/ask depth within 10 bps
        "avg_spread_bps": 1.0,         # Tight spread on SOL/USDT
        "fill_rate": 0.98,             # Market orders almost always fill
    },
    "coinbase": {
        "label": "Coinbase",
        "fee_numerator": 12,
        "fee_denominator": 10_000,     # ~0.12% avg (maker 0.06%, taker 0.18% Advanced)
        "slippage_model": "order_book",
        "capital_efficiency": 5.0,     # Shallower book than Binance for SOL
        "landing_rate_base": 0.97,
        "landing_rate_uncompetitive": 0.99,
        "avg_latency_slots": 0,
        "slot_time_ms": 80,            # Slightly slower API
        "tip_pct_of_profit": 0.0,
        "min_tip_lamports": 0,
        "compute_units": 0,
        "maker_fee_bps": 6,            # 0.06% maker (Advanced Trading)
        "taker_fee_bps": 18,           # 0.18% taker (Advanced Trading)
        "book_depth_usd": 2_000_000,   # SOL-USD depth thinner than Binance
        "avg_spread_bps": 2.0,         # Wider than Binance
        "fill_rate": 0.97,
    },
}

DEFAULT_VENUE = "aggregated"


class FillSimulator(Simulator):
    """Simulates realistic trade fills with venue-specific mechanics.

    Models the full execution pipeline:
    1. Fee deduction (venue-specific, applied before swap for Raydium)
    2. Price impact from AMM curve (constant product or CLMM approximation)
    3. Jito bundle landing probability (stochastic auction model)
    4. Tip cost deduction
    5. Execution latency jitter

    Config keys:
        venue (str): "raydium", "orca", "jupiter", "aggregated"
        random_seed (int): For reproducible backtests
        landing_model (str): "stochastic" (default) or "deterministic"
        competition (str): "moderate" (default), "low", "high"
        pool_depth_sol (float): Override estimated pool depth
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        venue_name = config.get("venue", DEFAULT_VENUE)
        self.venue = VENUE_PROFILES.get(venue_name, VENUE_PROFILES[DEFAULT_VENUE])
        self.venue_name = venue_name
        self.landing_model = config.get("landing_model", "stochastic")
        self.pool_depth = config.get(
            "pool_depth_sol",
            DEFAULT_POOL_DEPTH_SOL.get(venue_name, 50_000),
        )

        # Competition level affects landing rate
        competition = config.get("competition", "moderate")
        if competition == "low":
            self._landing_rate = self.venue["landing_rate_uncompetitive"]
        elif competition == "high":
            self._landing_rate = self.venue["landing_rate_base"] * 0.5
        else:
            self._landing_rate = self.venue["landing_rate_base"]

        seed = config.get("random_seed")
        self._rng = random.Random(seed)

        # Real order book data (set via set_book_data())
        self._book_data: dict[str, dict[str, float]] = {}
        self._has_real_book = False

        # Stats
        self._total_simulated = 0
        self._total_landed = 0
        self._total_profitable_after_costs = 0
        self._total_slippage_bps = 0.0

    def set_book_data(self, book_df: pl.DataFrame) -> None:
        """Load order book snapshots for realistic slippage.

        Expects a DataFrame with columns: timestamp (or ts_aligned),
        book_spread_bps (or spread_bps), book_bid_depth (or bid_depth),
        book_ask_depth (or ask_depth).

        The lookup key is the ISO-format timestamp truncated to the minute.
        During simulate(), if the opportunity's timestamp matches a key, the
        real book data replaces the venue-default estimates.

        Args:
            book_df: DataFrame containing order book snapshot columns, typically
                from a merged backtest Parquet that was prepared with an
                orderbook_path argument.
        """
        self._book_data = {}

        # Resolve column names — accept both raw and prefixed variants
        ts_col = "ts_aligned" if "ts_aligned" in book_df.columns else "timestamp"
        spread_col = (
            "book_spread_bps" if "book_spread_bps" in book_df.columns else "spread_bps"
        )
        bid_col = (
            "book_bid_depth" if "book_bid_depth" in book_df.columns else "bid_depth"
        )
        ask_col = (
            "book_ask_depth" if "book_ask_depth" in book_df.columns else "ask_depth"
        )

        if ts_col not in book_df.columns:
            logger.warning("fill_simulator.set_book_data.no_timestamp_column")
            return

        for row in book_df.iter_rows(named=True):
            ts = row.get(ts_col)
            if ts is None:
                continue
            key = str(ts)[:16]  # Key by minute: "2026-04-01T12:05"
            self._book_data[key] = {
                "spread_bps": float(row.get(spread_col) or 1.0),
                "bid_depth": float(row.get(bid_col) or 100.0),
                "ask_depth": float(row.get(ask_col) or 100.0),
            }

        self._has_real_book = len(self._book_data) > 0
        logger.info(
            "fill_simulator.book_data_loaded",
            entries=len(self._book_data),
            has_real_book=self._has_real_book,
        )

    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        """Simulate realistic fill for this opportunity."""
        self._total_simulated += 1

        trade_size_sol = opportunity.amount_in_lamports / LAMPORTS_PER_SOL
        if trade_size_sol <= 0:
            trade_size_sol = 0.01

        dex_price = opportunity.dex_price
        spread_bps = opportunity.spread_bps

        # ── Step 1: Calculate venue fee ──
        fee_bps = self._calc_fee_bps()

        # ── Step 2: Calculate price impact (slippage) ──
        slippage_bps = self._calc_price_impact(
            trade_size_sol, opportunity_ts=opportunity.detected_at
        )
        self._total_slippage_bps += slippage_bps

        # ── Step 3: State staleness — price may have moved ──
        # CEX: ~50-80ms latency, minimal decay
        # DEX: ~2 seconds (5 slots), significant decay
        latency_slots = self.venue["avg_latency_slots"]
        if self.venue.get("slippage_model") == "order_book":
            staleness_decay_bps = self._rng.random() * 0.5  # 0-0.5 bps for CEX
        else:
            staleness_decay_bps = self._calc_staleness_decay(latency_slots)

        # ── Step 4: Net spread after ALL costs ──
        total_cost_bps = fee_bps + slippage_bps + staleness_decay_bps
        net_spread_bps = spread_bps - total_cost_bps

        if net_spread_bps <= 0:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                gross_profit_sol=opportunity.estimated_profit_sol,
                net_profit_sol=0.0,
                sim_error=(
                    f"Unprofitable: {spread_bps:.1f} bps spread "
                    f"- {fee_bps:.1f} fee - {slippage_bps:.1f} slippage "
                    f"- {staleness_decay_bps:.1f} decay = {net_spread_bps:.1f} bps net"
                ),
                sim_latency_ms=latency_slots * self.venue["slot_time_ms"],
                simulated=True,
            )

        self._total_profitable_after_costs += 1

        # ── Step 5: Jito bundle landing check ──
        landed = self._check_landing()
        if not landed:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                gross_profit_sol=opportunity.estimated_profit_sol,
                net_profit_sol=0.0,
                sim_error=f"Bundle did not land ({self._landing_rate * 100:.0f}% rate)",
                sim_latency_ms=latency_slots * self.venue["slot_time_ms"],
                simulated=True,
            )

        self._total_landed += 1

        # ── Step 6: Calculate actual profit in integer lamports ──
        from mev_kit.utils.precision import sol_to_lamports, lamports_to_sol, mul_bps

        size_lamports = sol_to_lamports(trade_size_sol)
        # net_spread_bps is float from slippage calc — truncate to int for final math
        net_bps_i = int(net_spread_bps)
        net_profit_lam = (size_lamports * max(net_bps_i, 0)) // 10_000

        # Deduct tip (integer)
        tip_bps_i = int(self.venue["tip_pct_of_profit"] * 10_000)  # e.g., 0.10 → 1000 bps
        tip_lam = max(
            mul_bps(net_profit_lam, tip_bps_i),
            self.venue["min_tip_lamports"],
        )
        net_profit_lam -= tip_lam

        if net_profit_lam <= 0:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                gross_profit_sol=opportunity.estimated_profit_sol,
                net_profit_sol=0.0,
                sim_error=f"Tip ({lamports_to_sol(tip_lam):.6f} SOL) exceeds net profit",
                simulated=True,
            )

        # ── Step 7: Latency jitter ──
        jitter = 0.8 + self._rng.random() * 0.4
        latency_ms = latency_slots * self.venue["slot_time_ms"] * jitter

        return SimulationResult(
            opportunity_id=opportunity.id,
            profitable=True,
            gross_profit_sol=opportunity.estimated_profit_sol,
            net_profit_sol=lamports_to_sol(net_profit_lam),
            tip_lamports=tip_lam,
            priority_fee_lamports=0,
            compute_units=self.venue["compute_units"],
            sim_latency_ms=round(latency_ms, 1),
            simulated=True,
        )

    def _calc_fee_bps(self) -> float:
        """Calculate venue fee in basis points."""
        # CEX: use taker fee (market orders for MEV speed)
        if self.venue.get("slippage_model") == "order_book":
            return float(self.venue.get("taker_fee_bps", 10))
        # Jupiter: zero Jupiter fee, but underlying venue fees apply
        if self.venue_name == "jupiter":
            return float(self.venue.get("underlying_fee_bps", 25))
        # DEX: standard fee from pool config
        return self.venue["fee_numerator"] / self.venue["fee_denominator"] * 10_000

    def _calc_price_impact(
        self,
        trade_size_sol: float,
        opportunity_ts: Any | None = None,
    ) -> float:
        """Calculate price impact in bps using venue-specific model.

        DEX (constant product / CLMM):
            impact = trade_size / (reserve + trade_size)
            Adjusted by capital_efficiency for concentrated liquidity

        CEX (order book):
            impact = trade_value / book_depth × scaling_factor
            Much lower than DEX for equivalent liquidity
            Plus the bid-ask spread as a baseline cost
        """
        model = self.venue.get("slippage_model", "constant_product")

        if model == "order_book":
            # Look up real book data for this timestamp when available
            real_book: dict[str, float] | None = None
            if self._has_real_book and opportunity_ts is not None:
                key = str(opportunity_ts)[:16]
                real_book = self._book_data.get(key)
            return self._calc_orderbook_impact(trade_size_sol, real_book=real_book)

        # DEX: constant product with capital efficiency adjustment
        effective_reserve = self.pool_depth * self.venue["capital_efficiency"]

        # Constant product price impact: dx / (R + dx)
        impact_fraction = trade_size_sol / (effective_reserve + trade_size_sol)
        impact_bps = impact_fraction * 10_000

        # Add market microstructure noise (±30%)
        noise = 1.0 + (self._rng.random() - 0.5) * 0.6
        impact_bps *= noise

        return max(impact_bps, 0.1)

    def _calc_orderbook_impact(
        self,
        trade_size_sol: float,
        real_book: dict[str, float] | None = None,
    ) -> float:
        """Calculate order book slippage for CEX venues.

        Order book slippage = half-spread + market impact

        Half-spread: the cost of crossing from mid to best bid/ask.
        For Binance SOL/USDT: ~0.5-1 bps half-spread.
        For Coinbase SOL-USD: ~1-2 bps half-spread.

        Market impact: walking through the book beyond best price.
        Modeled as: (trade_value_usd / book_depth_usd) × 10000
        This is approximately square-root for large orders but
        linear for the small sizes MEV bots typically trade.

        Key difference from DEX: CEX has discrete price levels,
        partial fills at each level, and much deeper liquidity.

        When real_book is provided (from Tardis/Kaiko snapshot data),
        the empirical spread and depth replace the venue-profile estimates,
        giving a more accurate slippage figure for backtesting.

        Args:
            trade_size_sol: Trade size in SOL.
            real_book: Optional dict with keys ``spread_bps``, ``bid_depth``,
                ``ask_depth`` from a real order book snapshot.
        """
        if real_book is not None:
            # Use real empirical book data — spread is already in bps
            avg_spread_bps = real_book["spread_bps"]
            # Depths are in quote tokens (SOL units from Tardis); convert to USD
            # (rough: 1 SOL ~ $100 for impact calculation)
            book_depth_usd = (
                (real_book["bid_depth"] + real_book["ask_depth"]) / 2
            ) * 100
            if book_depth_usd < 1000:
                # Depth looks like it's already in USD or very small — use as-is
                book_depth_usd = max(book_depth_usd, 10_000)
        else:
            avg_spread_bps = self.venue.get("avg_spread_bps", 1.0)
            book_depth_usd = self.venue.get("book_depth_usd", 2_000_000)

        # Half-spread cost (crossing from mid to best bid/ask)
        half_spread = avg_spread_bps / 2.0

        # Estimate trade value in USD (rough: SOL ~ $80-150)
        trade_value_usd = trade_size_sol * 100  # ~$100/SOL estimate

        # Market impact: linear for small orders, sqrt for large
        # Linear regime: trade < 10% of top-of-book depth
        # sqrt regime: trade > 10% of book
        linear_impact_bps = (trade_value_usd / book_depth_usd) * 10_000

        if trade_value_usd > book_depth_usd * 0.1:
            # Large order — sqrt model (Almgren-Chriss)
            # impact ∝ sqrt(trade_size / daily_volume)
            impact_bps = math.sqrt(linear_impact_bps * 10_000) / 100
        else:
            impact_bps = linear_impact_bps

        # Add noise (±20% — CEX books are more stable than AMM)
        noise = 1.0 + (self._rng.random() - 0.5) * 0.4
        total = (half_spread + impact_bps) * noise

        return max(total, 0.05)

    def _calc_staleness_decay(self, latency_slots: int) -> float:
        """Model spread narrowing during execution latency.

        Between detection and bundle landing (~5 slots = 2 seconds),
        other traders may capture part of the spread. Model as:
        - Each slot has a probability of spread narrowing
        - On average, ~20-40% of the spread decays per second
        """
        decay_per_slot = 0.04 + self._rng.random() * 0.04  # 4-8% per slot
        total_decay_fraction = 1.0 - math.pow(1.0 - decay_per_slot, latency_slots)
        # Return decay as fraction of the original spread — caller subtracts from spread_bps
        # We return an ABSOLUTE bps amount, so we need the spread
        # But we don't have it here — return the fraction, caller will handle
        # Actually, let's model it as absolute: ~1-5 bps of decay for typical spreads
        return (1.0 + self._rng.random() * 3.0) * total_decay_fraction

    def _check_landing(self) -> bool:
        """Check if the Jito bundle would land in the auction."""
        if self.landing_model == "deterministic":
            return (self._total_simulated % 100) < (self._landing_rate * 100)
        return self._rng.random() < self._landing_rate
