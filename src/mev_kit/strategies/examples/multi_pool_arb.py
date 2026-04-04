"""Multi-pool atomic arbitrage detector.

Watches multiple Raydium/Orca pools and detects circular arbitrage routes
where a series of swaps yields more output than input. For example:

    SOL -> USDC (Pool A) -> RAY (Pool B) -> SOL (Pool C)

If the final SOL amount exceeds the initial SOL (after fees), an atomic
arb opportunity exists. All legs execute in a single Solana transaction.

REQUIRED_DATA_SOURCES:
    - Source.HELIUS_WS or Source.GEYSER: On-chain pool state updates
    - Source.PARQUET_REPLAY: For backtesting with historical pool data

Demonstrates:
    - process_batch(): returning multiple opportunities from one update
    - sync_state(): initializing pool graph before the event loop
    - Multi-pool state tracking
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    PoolState,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class MultiPoolArbDetector(Detector):
    """Detects circular arbitrage across multiple DEX pools.

    Maintains a graph of pool states and checks for profitable
    triangular routes on every pool update.

    Config keys:
        base_token (str): Token to start/end with. Default: "SOL"
        max_hops (int): Maximum legs in a route. Default: 3
        min_profit_bps (float): Minimum profit threshold. Default: 10.0
        position_size_sol (float): Trade size. Default: 0.1
    """

    required_sources = {Source.HELIUS_WS, Source.PARQUET_REPLAY}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.base_token: str = config.get("base_token", "SOL")
        self.max_hops: int = config.get("max_hops", 3)
        self.min_profit_bps: float = config.get("min_profit_bps", 10.0)
        self.position_size_sol: float = config.get("position_size_sol", 0.1)

        # pool_address -> latest PoolState
        self._pools: dict[str, PoolState] = {}
        # token -> list of pool addresses that trade that token
        self._token_pools: dict[str, list[str]] = defaultdict(list)

    async def sync_state(self) -> None:
        """Initialize the pool graph.

        In production, this would fetch current reserves for all
        known pools via RPC. Here we start empty and build state
        from incoming updates.
        """
        self._pools.clear()
        self._token_pools.clear()

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Single-opportunity interface; delegates to process_batch."""
        results = await self.process_batch(update)
        return results[0] if results else None

    async def process_batch(self, update: StateUpdate) -> list[Opportunity]:
        """Update pool state and scan for circular arb routes."""
        if not update.pool:
            return []

        pool = update.pool
        self._pools[pool.pool_address] = pool

        # Index by both tokens for route discovery
        if pool.pool_address not in self._token_pools[pool.base_mint]:
            self._token_pools[pool.base_mint].append(pool.pool_address)
        if pool.pool_address not in self._token_pools[pool.quote_mint]:
            self._token_pools[pool.quote_mint].append(pool.pool_address)

        # Need at least 2 pools for triangular arb
        if len(self._pools) < 2:
            return []

        opportunities: list[Opportunity] = []
        routes = self._find_routes(self.base_token, self.max_hops)

        for route in routes:
            profit_bps = self._simulate_route(route)
            if profit_bps >= self.min_profit_bps:
                estimated_profit = (profit_bps / 10_000) * self.position_size_sol
                self._opportunities_detected += 1
                opportunities.append(
                    Opportunity(
                        id=str(uuid.uuid4()),
                        type=OpportunityType.ATOMIC_ARB,
                        direction=Direction.BUY_DEX,
                        dex_price=self._pools[route[0]].price,
                        reference_price=self._pools[route[-1]].price,
                        spread_bps=round(profit_bps, 2),
                        estimated_profit_sol=estimated_profit,
                        pool_address=route[0],
                        dex=self._pools[route[0]].dex,
                        pair=f"{self.base_token}/multi",
                        amount_in_lamports=int(
                            self.position_size_sol * 1_000_000_000
                        ),
                        detector_name=self.name,
                        metadata={
                            "route": route,
                            "hops": len(route),
                            "profit_bps": round(profit_bps, 2),
                        },
                    )
                )

        return opportunities

    def _find_routes(
        self, start_token: str, max_hops: int
    ) -> list[list[str]]:
        """Find circular routes starting and ending with start_token.

        Uses DFS to explore paths through the pool graph up to
        max_hops length, returning only routes that form a cycle.
        """
        routes: list[list[str]] = []

        def _dfs(
            current_token: str,
            path: list[str],
            visited: set[str],
            depth: int,
        ) -> None:
            if depth > max_hops:
                return
            for pool_addr in self._token_pools.get(current_token, []):
                if pool_addr in visited:
                    continue
                pool = self._pools.get(pool_addr)
                if pool is None:
                    continue
                # Determine the output token for this swap
                if pool.base_mint == current_token:
                    next_token = pool.quote_mint
                elif pool.quote_mint == current_token:
                    next_token = pool.base_mint
                else:
                    continue

                new_path = path + [pool_addr]
                if next_token == start_token and len(new_path) >= 2:
                    routes.append(new_path)
                else:
                    _dfs(
                        next_token,
                        new_path,
                        visited | {pool_addr},
                        depth + 1,
                    )

        _dfs(start_token, [], set(), 0)
        return routes

    def _simulate_route(self, route: list[str]) -> float:
        """Estimate profit of executing a route, in basis points.

        Uses constant-product AMM math: output = (reserve_out * dx) / (reserve_in + dx).
        Accumulates fees at each hop.
        """
        amount = self.position_size_sol
        for pool_addr in route:
            pool = self._pools[pool_addr]
            fee_factor = 1.0 - (pool.fee_bps / 10_000)
            effective_in = amount * fee_factor
            # Determine swap direction
            if amount == self.position_size_sol and pool.base_reserve > 0:
                amount_out = (
                    pool.quote_reserve * effective_in
                ) / (pool.base_reserve + effective_in)
            else:
                if pool.quote_reserve > 0:
                    amount_out = (
                        pool.base_reserve * effective_in
                    ) / (pool.quote_reserve + effective_in)
                else:
                    return 0.0
            amount = amount_out

        if self.position_size_sol == 0:
            return 0.0
        return ((amount - self.position_size_sol) / self.position_size_sol) * 10_000
