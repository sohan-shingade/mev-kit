"""Lending protocol liquidation detector.

Monitors lending protocol positions (e.g., Solend, MarginFi) by tracking
collateral and debt prices. When a position's health factor drops below
the liquidation threshold, emits an Opportunity representing a profitable
liquidation call.

Liquidations on Solana lending protocols typically reward the liquidator
with a percentage of the seized collateral (the "liquidation bonus"),
making them a reliable MEV source.

REQUIRED_DATA_SOURCES:
    - Source.HELIUS_WS or Source.GEYSER: On-chain account updates for
      position health (obligation accounts)
    - Source.BINANCE_WS: Oracle price feed for collateral valuation

Demonstrates:
    - required_sources: multiple heterogeneous data feeds
    - warmup_updates: needing price history before reliable detection
    - Position tracking and health factor calculation
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


@dataclass
class LendingPosition:
    """Tracked lending position with collateral and debt values."""

    position_id: str
    borrower: str
    collateral_mint: str
    debt_mint: str
    collateral_amount: float
    debt_amount: float
    liquidation_threshold: float = 0.8  # LTV threshold
    liquidation_bonus_bps: float = 500.0  # 5% bonus


class LiquidationDetector(Detector):
    """Detects liquidatable lending protocol positions.

    Tracks positions and price feeds to compute real-time health
    factors. When health drops below threshold, emits an opportunity.

    Config keys:
        health_threshold (float): Health factor below which to trigger. Default: 1.05
        min_debt_usd (float): Minimum debt size to bother liquidating. Default: 10.0
        liquidation_bonus_bps (float): Expected bonus. Default: 500.0
        max_positions (int): Max positions to track. Default: 1000
    """

    required_sources = {Source.HELIUS_WS, Source.BINANCE_WS}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.health_threshold: float = config.get("health_threshold", 1.05)
        self.min_debt_usd: float = config.get("min_debt_usd", 10.0)
        self.liquidation_bonus_bps: float = config.get(
            "liquidation_bonus_bps", 500.0
        )
        self.max_positions: int = config.get("max_positions", 1000)

        # position_id -> LendingPosition
        self._positions: dict[str, LendingPosition] = {}
        # mint -> latest price
        self._prices: dict[str, float] = {}

    @property
    def warmup_updates(self) -> int:
        """Need at least 10 price updates to establish baselines."""
        return 10

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Check for liquidatable positions on every price update."""
        self._update_state(update)

        if not self.is_warmed_up:
            return None

        # Scan tracked positions for liquidation opportunities
        for pos in self._positions.values():
            health = self._compute_health(pos)
            if health is None:
                continue

            if health >= self.health_threshold:
                continue

            debt_usd = self._value_in_usd(pos.debt_mint, pos.debt_amount)
            if debt_usd is None or debt_usd < self.min_debt_usd:
                continue

            bonus_profit = debt_usd * (self.liquidation_bonus_bps / 10_000)
            collateral_price = self._prices.get(pos.collateral_mint, 0.0)
            debt_price = self._prices.get(pos.debt_mint, 1.0)

            self._opportunities_detected += 1

            return Opportunity(
                id=str(uuid.uuid4()),
                type=OpportunityType.LIQUIDATION,
                direction=Direction.BUY_DEX,
                dex_price=collateral_price,
                reference_price=debt_price,
                spread_bps=round(self.liquidation_bonus_bps, 2),
                estimated_profit_sol=bonus_profit / max(collateral_price, 0.01),
                pool_address=pos.position_id,
                dex="lending",
                pair=f"{pos.collateral_mint}/{pos.debt_mint}",
                amount_in_lamports=int(pos.debt_amount * 1_000_000_000),
                detector_name=self.name,
                metadata={
                    "borrower": pos.borrower,
                    "health_factor": round(health, 4),
                    "debt_usd": round(debt_usd, 2),
                    "collateral_amount": pos.collateral_amount,
                    "debt_amount": pos.debt_amount,
                },
            )

        return None

    def _update_state(self, update: StateUpdate) -> None:
        """Update prices and positions from incoming data."""
        self._updates_seen += 1

        if update.price:
            symbol = update.price.symbol
            self._prices[symbol] = update.price.price

        if update.pool:
            # Treat pool updates as implicit price sources
            self._prices[update.pool.base_mint] = update.pool.price

        # In production, position data comes from on-chain account
        # parsing. For backtesting, positions come from config.
        # We seed sample positions from config if provided.
        if not self._positions and "positions" in self.config:
            for p in self.config["positions"][:self.max_positions]:
                pos = LendingPosition(
                    position_id=p["position_id"],
                    borrower=p.get("borrower", "unknown"),
                    collateral_mint=p.get("collateral_mint", "SOL"),
                    debt_mint=p.get("debt_mint", "USDC"),
                    collateral_amount=p.get("collateral_amount", 100.0),
                    debt_amount=p.get("debt_amount", 5000.0),
                    liquidation_threshold=p.get("liquidation_threshold", 0.8),
                    liquidation_bonus_bps=p.get(
                        "liquidation_bonus_bps", self.liquidation_bonus_bps
                    ),
                )
                self._positions[pos.position_id] = pos

    def _compute_health(self, pos: LendingPosition) -> float | None:
        """Compute health factor: (collateral_value * threshold) / debt_value."""
        collateral_usd = self._value_in_usd(
            pos.collateral_mint, pos.collateral_amount
        )
        debt_usd = self._value_in_usd(pos.debt_mint, pos.debt_amount)
        if collateral_usd is None or debt_usd is None or debt_usd == 0:
            return None
        return (collateral_usd * pos.liquidation_threshold) / debt_usd

    def _value_in_usd(self, mint: str, amount: float) -> float | None:
        """Look up price for a mint and compute USD value."""
        price = self._prices.get(mint)
        if price is None:
            return None
        return amount * price
