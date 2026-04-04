"""Simple CEX-DEX spread tracker with cooldown logic.

Monitors the spread between a CEX reference price (Binance) and a DEX
pool price (Helius/Geyser). Emits an Opportunity when the spread exceeds
a configurable threshold, then enforces a cooldown period to avoid
flooding the pipeline with duplicate signals during sustained spreads.

This is the simplest practical detector and a good starting point for
understanding the Detector API.

REQUIRED_DATA_SOURCES:
    - Source.BINANCE_WS: CEX reference price feed
    - Source.HELIUS_WS or Source.PARQUET_REPLAY: DEX pool price feed

Demonstrates:
    - required_sources: declaring data dependencies
    - before() hook: updating internal state on every tick
    - Cooldown logic: suppressing repeated signals
"""

from __future__ import annotations

import time
import uuid

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class SpreadTracker(Detector):
    """Tracks CEX-DEX spread and emits opportunities with cooldown.

    Config keys:
        min_spread_bps (float): Minimum net spread to trigger. Default: 20.0
        fee_bps (float): DEX swap fee in basis points. Default: 30.0
        cooldown_sec (float): Seconds to suppress signals after detection. Default: 5.0
        pair (str): Trading pair. Default: "SOL/USDC"
        position_size_sol (float): Trade size. Default: 0.05
    """

    required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.min_spread_bps: float = config.get("min_spread_bps", 20.0)
        self.fee_bps: float = config.get("fee_bps", 30.0)
        self.cooldown_sec: float = config.get("cooldown_sec", 5.0)
        self.pair: str = config.get("pair", "SOL/USDC")
        self.position_size_sol: float = config.get("position_size_sol", 0.05)

        self._cex_price: float | None = None
        self._dex_price: float | None = None
        self._last_signal_time: float = 0.0
        self._current_spread_bps: float = 0.0

    async def before(self, update: StateUpdate) -> None:
        """Update internal prices on every tick, regardless of detection."""
        if update.source == Source.BINANCE_WS and update.price:
            self._cex_price = update.price.price
        elif update.pool:
            self._dex_price = update.pool.price
        elif update.price and update.source != Source.BINANCE_WS:
            self._dex_price = update.price.price

        if self._cex_price and self._dex_price and self._cex_price > 0:
            self._current_spread_bps = (
                abs(self._cex_price - self._dex_price) / self._cex_price * 10_000
            )

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Detect spread opportunity with cooldown enforcement."""
        if self._cex_price is None or self._dex_price is None:
            return None

        net_spread = self._current_spread_bps - self.fee_bps
        if net_spread < self.min_spread_bps:
            return None

        # Enforce cooldown to avoid duplicate signals
        now = time.monotonic()
        if (now - self._last_signal_time) < self.cooldown_sec:
            return None
        self._last_signal_time = now

        direction = (
            Direction.BUY_DEX
            if self._dex_price < self._cex_price
            else Direction.SELL_DEX
        )
        estimated_profit = (
            (net_spread / 10_000) * self.position_size_sol * self._cex_price
        )

        self._opportunities_detected += 1

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.CEX_DEX_ARB,
            direction=direction,
            dex_price=self._dex_price,
            reference_price=self._cex_price,
            spread_bps=round(net_spread, 2),
            estimated_profit_sol=estimated_profit / self._cex_price,
            pool_address="",
            dex="raydium",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "gross_spread_bps": round(self._current_spread_bps, 2),
                "cooldown_sec": self.cooldown_sec,
            },
        )
