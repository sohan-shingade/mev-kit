"""Price momentum detector for DEX price movements.

Identifies sustained directional moves in DEX prices by computing a
fast and slow moving average on incoming price ticks. When the fast MA
crosses above the slow MA, the detector signals a momentum opportunity
to buy on-chain. When it crosses below, it signals to sell.

Unlike mean-reversion strategies, momentum strategies benefit from
trending markets and lose in ranging markets. This detector is useful
as a signal filter or as a standalone strategy for tokens with strong
directional catalysts (e.g., token launches, governance votes).

REQUIRED_DATA_SOURCES:
    - Source.HELIUS_WS or Source.PARQUET_REPLAY: DEX pool price feed

Demonstrates:
    - warmup_updates: requires sufficient price history for MAs
    - Numpy-free moving average using a ring buffer
    - after() hook: tracking detection rate and cooldown
    - Simple but complete state machine for crossover detection
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


class MomentumDetector(Detector):
    """Detects momentum via fast/slow moving average crossover.

    Maintains two moving averages over DEX price ticks. Signals
    when the fast MA crosses the slow MA, indicating directional
    momentum.

    Config keys:
        fast_period (int): Fast MA window size. Default: 10
        slow_period (int): Slow MA window size. Default: 30
        min_separation_bps (float): Minimum distance between MAs. Default: 5.0
        pair (str): Trading pair. Default: "SOL/USDC"
        position_size_sol (float): Trade size. Default: 0.05
        cooldown_ticks (int): Ticks to suppress after signal. Default: 5
    """

    required_sources = {Source.HELIUS_WS, Source.PARQUET_REPLAY}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.fast_period: int = config.get("fast_period", 10)
        self.slow_period: int = config.get("slow_period", 30)
        self.min_separation_bps: float = config.get("min_separation_bps", 5.0)
        self.pair: str = config.get("pair", "SOL/USDC")
        self.position_size_sol: float = config.get("position_size_sol", 0.05)
        self.cooldown_ticks: int = config.get("cooldown_ticks", 5)

        # Ring buffers for numpy-free MA calculation
        self._fast_buf: deque[float] = deque(maxlen=self.fast_period)
        self._slow_buf: deque[float] = deque(maxlen=self.slow_period)
        self._fast_sum: float = 0.0
        self._slow_sum: float = 0.0

        # Crossover state
        self._prev_fast_above: bool | None = None
        self._ticks_since_signal: int = 0
        self._signal_count: int = 0

    @property
    def warmup_updates(self) -> int:
        """Need enough ticks to fill the slow MA buffer."""
        return self.slow_period

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Detect MA crossover events on DEX price updates."""
        price = self._extract_price(update)
        if price is None:
            return None

        self._updates_seen += 1
        self._ticks_since_signal += 1

        # Update fast MA ring buffer
        if len(self._fast_buf) == self._fast_buf.maxlen:
            self._fast_sum -= self._fast_buf[0]
        self._fast_buf.append(price)
        self._fast_sum += price

        # Update slow MA ring buffer
        if len(self._slow_buf) == self._slow_buf.maxlen:
            self._slow_sum -= self._slow_buf[0]
        self._slow_buf.append(price)
        self._slow_sum += price

        if not self.is_warmed_up:
            return None

        fast_ma = self._fast_sum / len(self._fast_buf)
        slow_ma = self._slow_sum / len(self._slow_buf)

        if slow_ma == 0:
            return None

        # Check MA separation
        separation_bps = abs(fast_ma - slow_ma) / slow_ma * 10_000
        if separation_bps < self.min_separation_bps:
            self._prev_fast_above = fast_ma > slow_ma
            return None

        fast_above = fast_ma > slow_ma

        # Detect crossover
        if self._prev_fast_above is None:
            self._prev_fast_above = fast_above
            return None

        crossed = fast_above != self._prev_fast_above
        self._prev_fast_above = fast_above

        if not crossed:
            return None

        # Enforce cooldown
        if self._ticks_since_signal < self.cooldown_ticks:
            return None
        self._ticks_since_signal = 0

        direction = Direction.BUY if fast_above else Direction.SELL
        estimated_profit = (
            (separation_bps / 10_000) * self.position_size_sol * price
        )

        self._opportunities_detected += 1

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.STATISTICAL_ARB,
            direction=direction,
            dex_price=price,
            reference_price=slow_ma,
            spread_bps=round(separation_bps, 2),
            estimated_profit_sol=estimated_profit / price,
            pool_address="",
            dex="raydium",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "fast_ma": round(fast_ma, 4),
                "slow_ma": round(slow_ma, 4),
                "separation_bps": round(separation_bps, 2),
                "crossover": "bullish" if fast_above else "bearish",
                "signal_number": self._opportunities_detected,
            },
        )

    async def after(
        self, update: StateUpdate, opportunities: list[Opportunity]
    ) -> None:
        """Track signal frequency for monitoring."""
        if opportunities:
            self._signal_count += 1

    def _extract_price(self, update: StateUpdate) -> float | None:
        """Extract DEX price from a StateUpdate."""
        if update.pool:
            return update.pool.price
        if update.price and update.source != Source.BINANCE_WS:
            return update.price.price
        return None
