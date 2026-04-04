"""Mean reversion / statistical arbitrage detector.

Monitors the CEX-DEX spread and compares it to a rolling historical mean.
When the current spread deviates significantly from the mean (measured in
standard deviations), emits an opportunity betting on reversion.

This is a classic pairs-trading approach applied to the CEX-DEX price
relationship. It works best in ranging markets where the spread oscillates
around a stable mean, and poorly in trending markets where the spread
drifts persistently.

REQUIRED_DATA_SOURCES:
    - Source.BINANCE_WS: CEX reference price for spread calculation
    - Source.HELIUS_WS or Source.PARQUET_REPLAY: DEX price feed

Demonstrates:
    - hyperparameters(): declaring optimizable parameter ranges
    - filters(): post-detection validation functions
    - before() hook: accumulating spread history every tick
    - warmup_updates: waiting for enough data to compute statistics
"""

from __future__ import annotations

import math
import uuid
from collections import deque

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class StatisticalArbDetector(Detector):
    """Mean-reversion detector using rolling spread z-score.

    Config keys:
        window_size (int): Rolling window for mean/std. Default: 100
        z_threshold (float): Z-score to trigger. Default: 2.0
        min_spread_bps (float): Floor on net spread. Default: 5.0
        fee_bps (float): DEX swap fee in basis points. Default: 30.0
        pair (str): Trading pair. Default: "SOL/USDC"
        position_size_sol (float): Trade size. Default: 0.05
    """

    required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.window_size: int = config.get("window_size", 100)
        self.z_threshold: float = config.get("z_threshold", 2.0)
        self.min_spread_bps: float = config.get("min_spread_bps", 5.0)
        self.fee_bps: float = config.get("fee_bps", 30.0)
        self.pair: str = config.get("pair", "SOL/USDC")
        self.position_size_sol: float = config.get("position_size_sol", 0.05)

        self._cex_price: float | None = None
        self._dex_price: float | None = None
        self._spread_history: deque[float] = deque(maxlen=self.window_size)
        # Running sums for incremental mean/variance
        self._sum: float = 0.0
        self._sum_sq: float = 0.0

    @property
    def warmup_updates(self) -> int:
        """Need a full window of spread observations."""
        return self.window_size

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        """Expose tunable parameters for backtesting grid search."""
        return {
            "z_threshold": (1.0, 4.0, 0.5),
            "window_size": (20.0, 500.0, 20.0),
            "min_spread_bps": (1.0, 20.0, 2.0),
            "position_size_sol": (0.01, 1.0, 0.1),
        }

    def filters(self) -> list:
        """Apply sanity filters after detection."""
        return [self._spread_sanity_filter, self._z_score_cap_filter]

    def _spread_sanity_filter(self, opp: Opportunity) -> bool:
        """Reject opportunities with unrealistically large spreads."""
        return opp.spread_bps < 500

    def _z_score_cap_filter(self, opp: Opportunity) -> bool:
        """Reject extreme z-scores that likely indicate bad data."""
        z = abs(opp.metadata.get("z_score", 0.0))
        return z < 10.0

    async def before(self, update: StateUpdate) -> None:
        """Track prices and accumulate spread history."""
        self._updates_seen += 1

        if update.source == Source.BINANCE_WS and update.price:
            self._cex_price = update.price.price
        elif update.pool:
            self._dex_price = update.pool.price
        elif update.price and update.source != Source.BINANCE_WS:
            self._dex_price = update.price.price

        # Record spread observation
        if self._cex_price and self._dex_price and self._cex_price > 0:
            spread = (
                (self._dex_price - self._cex_price) / self._cex_price * 10_000
            )
            # Update running sums for O(1) mean/std
            if len(self._spread_history) == self._spread_history.maxlen:
                old = self._spread_history[0]
                self._sum -= old
                self._sum_sq -= old * old
            self._spread_history.append(spread)
            self._sum += spread
            self._sum_sq += spread * spread

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Detect when spread z-score exceeds threshold."""
        if not self.is_warmed_up:
            return None
        if self._cex_price is None or self._dex_price is None:
            return None

        n = len(self._spread_history)
        if n < 2:
            return None

        mean = self._sum / n
        variance = (self._sum_sq / n) - (mean * mean)
        if variance <= 0:
            return None
        std = math.sqrt(variance)

        current_spread = self._spread_history[-1]
        z_score = (current_spread - mean) / std

        if abs(z_score) < self.z_threshold:
            return None

        # Net spread after fees
        net_spread_bps = abs(current_spread) - self.fee_bps
        if net_spread_bps < self.min_spread_bps:
            return None

        # Positive z-score = DEX expensive, sell on DEX
        # Negative z-score = DEX cheap, buy on DEX
        direction = Direction.SELL_DEX if z_score > 0 else Direction.BUY_DEX

        estimated_profit = (
            (net_spread_bps / 10_000) * self.position_size_sol * self._cex_price
        )

        self._opportunities_detected += 1

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.STATISTICAL_ARB,
            direction=direction,
            dex_price=self._dex_price,
            reference_price=self._cex_price,
            spread_bps=round(net_spread_bps, 2),
            estimated_profit_sol=estimated_profit / self._cex_price,
            pool_address="",
            dex="raydium",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "z_score": round(z_score, 3),
                "spread_mean_bps": round(mean, 2),
                "spread_std_bps": round(std, 2),
                "current_spread_bps": round(current_spread, 2),
                "window_size": self.window_size,
            },
        )
