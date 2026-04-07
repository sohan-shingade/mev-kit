"""CEX-DEX Arbitrage Detector — reference strategy implementation.

Detects price discrepancies between a CEX reference price (e.g., Binance)
and an on-chain DEX pool price (e.g., Raydium). When the spread exceeds
a configurable threshold, emits an Opportunity.

This is the simplest useful MEV strategy and serves as the template
for all custom detectors.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class CEXDEXArbDetector(Detector):
    """Detects CEX-DEX arbitrage opportunities.

    Maintains latest prices from both CEX and DEX sources.
    On every update, checks if the spread exceeds the minimum threshold.

    Config keys:
        min_spread_bps (float): Minimum net spread to trigger. Default: 15.0
        fee_bps (float): DEX swap fee in basis points. Default: 30.0
        pair (str): Trading pair to monitor. Default: "SOL/USDC"
        position_size_sol (float): Size of arb trade. Default: 0.01
    """

    # Declare required data sources for pipeline validation
    required_sources = {
        Source.BINANCE_WS,
        Source.COINBASE_WS,
        Source.HELIUS_WS,
        Source.YELLOWSTONE_GRPC,
        Source.GEYSER,
        Source.PARQUET_REPLAY,
    }

    # Sources we treat as CEX reference prices
    CEX_SOURCES = {Source.BINANCE_WS, Source.COINBASE_WS}

    # Sources we treat as DEX prices
    DEX_SOURCES = {Source.HELIUS_WS, Source.YELLOWSTONE_GRPC, Source.GEYSER, Source.PARQUET_REPLAY}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.min_spread_bps: float = config.get("min_spread_bps", 15.0)
        self.fee_bps: float = config.get("fee_bps", 30.0)
        self.pair: str = config.get("pair", "SOL/USDC")
        self.position_size_sol: float = config.get("position_size_sol", 0.01)

        # Internal state
        self._cex_price: float | None = None
        self._dex_price: float | None = None
        self._dex_pool_address: str = ""
        self._dex_name: str = ""
        self._last_cex_update: datetime | None = None
        self._last_dex_update: datetime | None = None
        self._last_volume: float | None = None

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a state update and check for arb opportunity."""

        # Update internal prices
        if update.source in self.CEX_SOURCES and update.price:
            self._cex_price = update.price.price
            self._last_cex_update = update.received_at
            if update.price.volume is not None:
                self._last_volume = update.price.volume

        elif update.source in self.DEX_SOURCES:
            if update.pool:
                self._dex_price = update.pool.price
                self._dex_pool_address = update.pool.pool_address
                self._dex_name = update.pool.dex
                self._last_dex_update = update.received_at
            elif update.price:
                self._dex_price = update.price.price
                self._last_dex_update = update.received_at
                if update.price.volume is not None:
                    self._last_volume = update.price.volume

        # Need both prices to detect
        if self._cex_price is None or self._dex_price is None:
            return None

        # Calculate spread using integer basis points
        from mev_kit.utils.precision import (
            spread_bps_int,
            profit_lamports,
            sol_to_lamports,
            lamports_to_sol,
        )

        gross_bps = spread_bps_int(self._cex_price, self._dex_price)
        fee_bps_i = int(self.fee_bps)
        net_bps = gross_bps - fee_bps_i

        if net_bps < int(self.min_spread_bps):
            return None

        # Determine direction
        if self._dex_price < self._cex_price:
            direction = Direction.BUY_DEX  # Buy cheap on DEX
        else:
            direction = Direction.SELL_DEX  # Sell expensive on DEX

        # Estimate profit in integer lamports
        size_lamports = sol_to_lamports(self.position_size_sol)
        est_profit_lamports = profit_lamports(
            spread_bps=gross_bps, fee_bps=fee_bps_i,
            size_lamports=size_lamports,
        )

        self._opportunities_detected += 1

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.CEX_DEX_ARB,
            direction=direction,
            dex_price=self._dex_price,
            reference_price=self._cex_price,
            spread_bps=float(net_bps),
            estimated_profit_sol=lamports_to_sol(est_profit_lamports),
            pool_address=self._dex_pool_address,
            dex=self._dex_name,
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "cex_price": self._cex_price,
                "dex_price": self._dex_price,
                "gross_spread_bps": float(gross_bps),
                "fee_bps": self.fee_bps,
                "volume": self._last_volume,
            },
        )

    # ── Filters (new Detector API) ──

    def filters(self) -> list:
        """Apply sanity filters to detected opportunities."""
        return [self._spread_sanity_filter]

    def _spread_sanity_filter(self, opp: Opportunity) -> bool:
        """Reject obviously wrong spreads (data glitches, stale prices)."""
        return opp.spread_bps < 1000
