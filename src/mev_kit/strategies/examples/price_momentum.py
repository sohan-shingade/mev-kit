"""Price momentum detector for Binance OHLCV (price-only) data.

Detects significant directional price movements over consecutive
updates. Unlike the CEX-DEX arb detector, this works with a single
data source --- specifically Binance 1-minute OHLCV Parquet files ---
making it the ideal default for first-time backtests.

REQUIRED_DATA_SOURCES:
    - source_type="price" Parquet data with columns:
      symbol, price (or close), volume, timestamp

Algorithm:
    Track the percentage change across the last N consecutive updates.
    When the cumulative move exceeds a configurable threshold, emit
    an opportunity in the direction of the move.

Demonstrates:
    - Single-source detector (works with Binance-only Parquet data)
    - required_sources declaration
    - Hyperparameters for optimizer sweeps
    - Filters for sanity checking
    - warmup_updates for price history accumulation
"""

from __future__ import annotations

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


class PriceMomentumDetector(Detector):
    """Detects significant price momentum from price-only data.

    Monitors a rolling window of price updates and fires when the
    cumulative percentage change exceeds a threshold. Designed to
    work with Binance OHLCV Parquet files replayed via
    ParquetReplayAdapter with source_type="price".

    Config keys:
        window_size (int): Number of consecutive updates to track. Default: 5
        threshold_pct (float): Min cumulative move (%) to trigger. Default: 0.3
        pair (str): Trading pair label. Default: "SOL/USDC"
        position_size_sol (float): Notional trade size. Default: 0.05
        cooldown_ticks (int): Updates to suppress after a signal. Default: 3
        min_volume (float): Minimum volume to consider an update. Default: 0.0
    """

    required_sources = {Source.PARQUET_REPLAY, Source.BINANCE_WS}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.window_size: int = config.get("window_size", 5)
        self.threshold_pct: float = config.get("threshold_pct", 0.3)
        self.pair: str = config.get("pair", "SOL/USDC")
        self.position_size_sol: float = config.get("position_size_sol", 0.05)
        self.cooldown_ticks: int = config.get("cooldown_ticks", 3)
        self.min_volume: float = config.get("min_volume", 0.0)

        # Internal state
        self._price_history: deque[float] = deque(maxlen=self.window_size + 1)
        self._ticks_since_signal: int = self.cooldown_ticks  # start ready
        self._last_price: float = 0.0

    @property
    def warmup_updates(self) -> int:
        """Need enough price history to fill the window."""
        return self.window_size + 1

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Detect momentum from price updates."""
        price = self._extract_price(update)
        if price is None or price <= 0:
            return None

        volume = self._extract_volume(update)
        if volume is not None and volume < self.min_volume:
            return None

        self._updates_seen += 1
        self._ticks_since_signal += 1
        self._price_history.append(price)
        self._last_price = price

        if not self.is_warmed_up:
            return None

        # Calculate cumulative percentage change over the window
        oldest = self._price_history[0]
        if oldest <= 0:
            return None

        pct_change = (price - oldest) / oldest * 100.0

        if abs(pct_change) < self.threshold_pct:
            return None

        # Enforce cooldown
        if self._ticks_since_signal < self.cooldown_ticks:
            return None
        self._ticks_since_signal = 0

        # Determine direction
        if pct_change > 0:
            direction = Direction.BUY_DEX  # Momentum up, buy signal
        else:
            direction = Direction.SELL_DEX  # Momentum down, sell signal

        spread_bps = abs(pct_change) * 100  # convert % to bps
        estimated_profit = (abs(pct_change) / 100.0) * self.position_size_sol

        self._opportunities_detected += 1

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.STATISTICAL_ARB,
            direction=direction,
            dex_price=price,
            reference_price=oldest,
            spread_bps=round(spread_bps, 2),
            estimated_profit_sol=round(estimated_profit, 6),
            pool_address="",
            dex="binance",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "pct_change": round(pct_change, 4),
                "window_size": self.window_size,
                "oldest_price": round(oldest, 4),
                "current_price": round(price, 4),
                "volume": volume,
                "direction": "bullish" if pct_change > 0 else "bearish",
            },
        )

    def filters(self) -> list:
        """Sanity-check detected opportunities."""
        return [self._max_spread_filter]

    def _max_spread_filter(self, opp: Opportunity) -> bool:
        """Reject obviously anomalous moves (data errors, flash wicks)."""
        return opp.spread_bps < 5000  # 50% move is almost certainly bad data

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        """Declare optimizable parameters for backtesting sweeps."""
        return {
            "window_size": (3.0, 20.0, 1.0),
            "threshold_pct": (0.1, 2.0, 0.1),
            "position_size_sol": (0.01, 1.0, 0.1),
            "cooldown_ticks": (1.0, 10.0, 1.0),
        }

    def _extract_price(self, update: StateUpdate) -> float | None:
        """Extract price from a StateUpdate, handling both pool and price types."""
        if update.price:
            return update.price.price
        if update.pool:
            return update.pool.price
        return None

    def _extract_volume(self, update: StateUpdate) -> float | None:
        """Extract volume if available."""
        if update.price and update.price.volume is not None:
            return update.price.volume
        return None
