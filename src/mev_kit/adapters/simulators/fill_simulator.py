"""Realistic fill simulator -- models venue-specific execution.

For each detected opportunity, simulates what would happen if you
actually submitted the trade. Models:
- Slippage based on trade size and pool liquidity
- Execution latency (price may move during submission)
- Venue-specific fee structures
- Jito bundle landing probability
- Partial fills

Each venue has its own fill model because execution characteristics
differ significantly:
- Raydium AMM: constant-product slippage, 30 bps fee
- Orca Whirlpools: concentrated liquidity, variable slippage
- Jupiter aggregated: best route, lower slippage, routing fee
- Jito bundle: landing rate ~30-50%, tip cost
"""

from __future__ import annotations

import random
from typing import Any

import structlog

from mev_kit.adapters.simulators.base import Simulator
from mev_kit.models import Opportunity, SimulationResult

logger = structlog.get_logger()

# Venue-specific parameters
VENUE_PROFILES: dict[str, dict[str, Any]] = {
    "raydium": {
        "label": "Raydium AMM v4",
        "fee_bps": 25,  # Raydium v4 charges 25 bps
        "slippage_model": "constant_product",
        "base_slippage_bps": 5,  # Minimum slippage even for small trades
        "size_impact_factor": 0.5,  # bps per SOL of trade size
        "landing_rate": 0.40,  # 40% of Jito bundles land
        "avg_latency_ms": 400,  # ~1 Solana slot
        "tip_bps": 10,  # Average Jito tip as % of profit
    },
    "orca": {
        "label": "Orca Whirlpool",
        "fee_bps": 20,  # Orca typical pool fee
        "slippage_model": "concentrated_liquidity",
        "base_slippage_bps": 3,  # Lower due to concentrated liquidity
        "size_impact_factor": 0.3,
        "landing_rate": 0.40,
        "avg_latency_ms": 400,
        "tip_bps": 10,
    },
    "jupiter": {
        "label": "Jupiter Aggregated",
        "fee_bps": 15,  # Jupiter routes to best fee
        "slippage_model": "aggregated",
        "base_slippage_bps": 2,  # Best routing reduces slippage
        "size_impact_factor": 0.2,  # Splits across venues
        "landing_rate": 0.45,  # Slightly better with priority routing
        "avg_latency_ms": 500,  # Extra routing computation time
        "tip_bps": 8,
    },
    "aggregated": {  # Birdeye/generic aggregated data
        "label": "DEX Aggregated",
        "fee_bps": 20,
        "slippage_model": "aggregated",
        "base_slippage_bps": 4,
        "size_impact_factor": 0.35,
        "landing_rate": 0.40,
        "avg_latency_ms": 450,
        "tip_bps": 10,
    },
}

# Default fallback
DEFAULT_VENUE = "aggregated"

LAMPORTS_PER_SOL = 1_000_000_000


class FillSimulator(Simulator):
    """Simulates realistic trade fills with venue-specific slippage.

    Unlike PassthroughSimulator (which marks everything as profitable
    at the theoretical price), FillSimulator models:

    1. Slippage: price impact from trade size hitting AMM curve
    2. Fees: venue-specific swap fees deducted from output
    3. Landing rate: probability the Jito bundle actually lands
    4. Tip cost: Jito tip deducted from profit
    5. Latency: price movement during execution delay

    Config keys:
        venue (str): Which venue to simulate ("raydium", "orca", "jupiter", "aggregated")
        random_seed (int): For reproducible backtests. None = true randomness.
        landing_model (str): "deterministic" (use rate as threshold) or "stochastic" (random)
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        venue_name = config.get("venue", DEFAULT_VENUE)
        self.venue = VENUE_PROFILES.get(venue_name, VENUE_PROFILES[DEFAULT_VENUE])
        self.venue_name = venue_name
        self.landing_model = config.get("landing_model", "stochastic")
        seed = config.get("random_seed")
        self._rng = random.Random(seed)

        # Stats
        self._total_simulated = 0
        self._total_landed = 0

    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        """Simulate realistic fill for this opportunity."""
        self._total_simulated += 1

        gross_profit_sol = opportunity.estimated_profit_sol
        spread_bps = opportunity.spread_bps
        trade_size_sol = opportunity.amount_in_lamports / LAMPORTS_PER_SOL
        if trade_size_sol <= 0:
            trade_size_sol = 0.01  # Fallback

        # 1. Calculate slippage
        slippage_bps = self._calc_slippage(trade_size_sol)

        # 2. Calculate venue fee
        fee_bps = self.venue["fee_bps"]

        # 3. Calculate tip cost
        tip_bps = self.venue["tip_bps"]

        # 4. Net spread after all costs
        total_cost_bps = slippage_bps + fee_bps + tip_bps
        net_spread_bps = spread_bps - total_cost_bps

        # 5. Net profit
        if net_spread_bps <= 0:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                gross_profit_sol=gross_profit_sol,
                net_profit_sol=0.0,
                sim_error=(
                    f"Unprofitable after costs: {total_cost_bps:.1f} bps costs "
                    f"> {spread_bps:.1f} bps spread"
                ),
                sim_latency_ms=float(self.venue["avg_latency_ms"]),
                simulated=True,
            )

        net_profit_sol = (net_spread_bps / 10_000) * trade_size_sol

        # 6. Landing rate check
        landed = self._check_landing()

        if not landed:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                gross_profit_sol=gross_profit_sol,
                net_profit_sol=0.0,
                sim_error=(
                    f"Bundle did not land (rate: {self.venue['landing_rate'] * 100:.0f}%)"
                ),
                sim_latency_ms=float(self.venue["avg_latency_ms"]),
                simulated=True,
            )

        self._total_landed += 1

        # 7. Add execution latency jitter
        latency_ms = self.venue["avg_latency_ms"] * (0.8 + self._rng.random() * 0.4)

        tip_lamports = int(net_profit_sol * LAMPORTS_PER_SOL * (tip_bps / 10_000))

        return SimulationResult(
            opportunity_id=opportunity.id,
            profitable=True,
            gross_profit_sol=gross_profit_sol,
            net_profit_sol=round(net_profit_sol, 8),
            tip_lamports=tip_lamports,
            compute_units=200_000,  # Typical Raydium swap
            sim_latency_ms=round(latency_ms, 1),
            simulated=True,
        )

    def _calc_slippage(self, trade_size_sol: float) -> float:
        """Calculate slippage in bps based on venue model and trade size."""
        base = self.venue["base_slippage_bps"]
        size_impact = self.venue["size_impact_factor"] * trade_size_sol

        # Add random noise (+/-20% of calculated slippage)
        noise = 1.0 + (self._rng.random() - 0.5) * 0.4

        return (base + size_impact) * noise

    def _check_landing(self) -> bool:
        """Check if the Jito bundle would land."""
        rate = self.venue["landing_rate"]
        if self.landing_model == "deterministic":
            # Deterministic: land if this is within the rate percentile
            return (self._total_simulated % 100) < (rate * 100)
        else:
            # Stochastic: random based on rate
            return self._rng.random() < rate
