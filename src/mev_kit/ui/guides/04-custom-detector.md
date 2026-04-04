# Writing a Custom Detector

## Overview

A Detector is the second layer of the mev-kit pipeline. It receives `StateUpdate` objects emitted by an `IngestAdapter` and decides whether to emit an `Opportunity`. Writing your own detector is the primary way to implement a new MEV strategy without touching any other part of the pipeline.

This guide walks through building a complete, working `SpreadTracker` detector from scratch. By the end, you will have a detector that:

1. Tracks the CEX (Binance) and DEX (Raydium) price for SOL/USDC
2. Computes the gross and net spread on every update
3. Emits an `Opportunity` whenever the net spread exceeds a configurable threshold
4. Respects a cooldown to avoid emitting duplicate opportunities on the same price spike

---

## Prerequisites

Install mev-kit in development mode:

```bash
pip install -e ".[dev]"
```

Your detector file will live at:

```
src/mev_kit/strategies/spread_tracker.py
```

Its test file will live at:

```
tests/unit/test_spread_tracker.py
```

---

## The Detector Abstract Base Class

Every detector inherits from `Detector` in `src/mev_kit/strategies/base.py`:

```python
# src/mev_kit/strategies/base.py
from abc import ABC, abstractmethod
from mev_kit.models.state import StateUpdate
from mev_kit.models.opportunity import Opportunity

class Detector(ABC):
    """Abstract base class for all MEV opportunity detectors."""

    @abstractmethod
    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a single StateUpdate.

        Args:
            update: A StateUpdate emitted by an IngestAdapter. May be a
                    PriceUpdate, PoolState, or AccountUpdate.

        Returns:
            An Opportunity if one was detected, or None.
        """
        ...
```

You implement exactly one method: `async def process`. It receives a `StateUpdate` and returns either an `Opportunity` or `None`. The pipeline calls this method for every incoming update — your implementation must be fast.

---

## Understanding StateUpdate Types

`StateUpdate` is a type alias for the union of all update types. In practice your detector will inspect the type of the incoming update and dispatch accordingly:

```python
from mev_kit.models.state import StateUpdate, PriceUpdate, PoolState, AccountUpdate

async def process(self, update: StateUpdate) -> Opportunity | None:
    if isinstance(update, PriceUpdate):
        # handle CEX price tick
        ...
    elif isinstance(update, PoolState):
        # handle DEX pool state
        ...
    else:
        return None  # ignore other update types
```

`PriceUpdate` fields:
- `source: str` — e.g., `"binance"`
- `symbol: str` — e.g., `"SOLUSDC"`
- `bid: float`, `ask: float`
- `timestamp_ms: int`

`PoolState` fields:
- `pool_address: str` — Solana account address
- `base_mint: str`, `quote_mint: str`
- `reserve_base: float`, `reserve_quote: float`
- `fee_bps: int` — pool fee in basis points
- `timestamp_ms: int`

---

## Understanding the Opportunity Model

`Opportunity` is defined in `src/mev_kit/models/opportunity.py`. All fields are required unless otherwise noted:

```python
from mev_kit.models.opportunity import Opportunity, OpportunityType

opp = Opportunity(
    opportunity_type=OpportunityType.CEX_DEX_ARB_BUY,
    pool_address="8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ",  # Raydium SOL/USDC
    cex_price=180.50,
    dex_price=180.00,
    spread_bps=27.7,
    net_spread_bps=12.7,
    estimated_profit_usd=0.064,
    position_size_usd=500.0,
    detected_at_ms=1712345678901,
)
```

`OpportunityType` values:
- `CEX_DEX_ARB_BUY` — DEX price is below CEX price, buy on DEX
- `CEX_DEX_ARB_SELL` — DEX price is above CEX price, sell on DEX

---

## Complete Implementation: SpreadTracker

Here is the complete `SpreadTracker` detector:

```python
# src/mev_kit/strategies/spread_tracker.py
"""Simple spread-tracking CEX-DEX arb detector.

Tracks the mid-price spread between a Binance price feed and a Raydium
pool. Emits an Opportunity whenever the net spread exceeds min_spread_bps.
A cooldown_ms parameter prevents emitting duplicate opportunities during
a single price spike.
"""

import time
import structlog

from mev_kit.models.opportunity import Opportunity, OpportunityType
from mev_kit.models.state import PoolState, PriceUpdate, StateUpdate
from mev_kit.strategies.base import Detector

logger = structlog.get_logger(__name__)


class SpreadTracker(Detector):
    """Detects CEX-DEX arbitrage opportunities by tracking bid/ask spreads.

    Args:
        pool_address: Solana address of the Raydium pool to monitor.
        cex_symbol: Binance symbol to subscribe to (e.g. "SOLUSDC").
        min_spread_bps: Minimum net spread in basis points to emit an Opportunity.
        position_size_usd: USD position size for profit estimation.
        fee_bps: DEX swap fee in basis points (default 30 for Raydium).
        cooldown_ms: Minimum milliseconds between emitted opportunities.
    """

    def __init__(
        self,
        pool_address: str,
        cex_symbol: str,
        min_spread_bps: float = 50.0,
        position_size_usd: float = 100.0,
        fee_bps: int = 30,
        cooldown_ms: int = 2_000,
    ) -> None:
        self.pool_address = pool_address
        self.cex_symbol = cex_symbol
        self.min_spread_bps = min_spread_bps
        self.position_size_usd = position_size_usd
        self.fee_bps = fee_bps
        self.cooldown_ms = cooldown_ms

        # Internal state updated on every relevant tick
        self._cex_mid: float | None = None
        self._dex_price: float | None = None
        self._last_emit_ms: int = 0

    # ------------------------------------------------------------------
    # Detector interface
    # ------------------------------------------------------------------

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a single StateUpdate and return an Opportunity if detected."""
        if isinstance(update, PriceUpdate):
            return await self._handle_price_update(update)
        elif isinstance(update, PoolState):
            return await self._handle_pool_state(update)
        return None

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _handle_price_update(self, update: PriceUpdate) -> Opportunity | None:
        """Update internal CEX price state from a Binance tick."""
        if update.symbol != self.cex_symbol:
            return None

        self._cex_mid = (update.bid + update.ask) / 2.0
        logger.debug(
            "cex_price_updated",
            symbol=update.symbol,
            mid=self._cex_mid,
        )
        return self._maybe_emit_opportunity()

    async def _handle_pool_state(self, update: PoolState) -> Opportunity | None:
        """Update internal DEX price state from a Raydium pool update."""
        if update.pool_address != self.pool_address:
            return None

        if update.reserve_base <= 0:
            logger.warning("pool_state_invalid", pool=update.pool_address)
            return None

        self._dex_price = update.reserve_quote / update.reserve_base
        logger.debug(
            "dex_price_updated",
            pool=update.pool_address,
            price=self._dex_price,
        )
        return self._maybe_emit_opportunity()

    # ------------------------------------------------------------------
    # Spread calculation and opportunity emission
    # ------------------------------------------------------------------

    def _maybe_emit_opportunity(self) -> Opportunity | None:
        """Check spread and emit Opportunity if conditions are met."""
        if self._cex_mid is None or self._dex_price is None:
            # Need both sides before we can compute a spread
            return None

        now_ms = int(time.time() * 1_000)
        if now_ms - self._last_emit_ms < self.cooldown_ms:
            # Within cooldown window — suppress duplicate signals
            return None

        gross_spread_bps = self._calculate_spread_bps(self._cex_mid, self._dex_price)
        net_spread_bps = gross_spread_bps - self.fee_bps

        if net_spread_bps < self.min_spread_bps:
            logger.debug(
                "spread_below_threshold",
                gross_bps=round(gross_spread_bps, 2),
                net_bps=round(net_spread_bps, 2),
                threshold=self.min_spread_bps,
            )
            return None

        direction = self._determine_direction(self._cex_mid, self._dex_price)
        estimated_profit_usd = (net_spread_bps / 10_000) * self.position_size_usd

        self._last_emit_ms = now_ms

        opp = Opportunity(
            opportunity_type=direction,
            pool_address=self.pool_address,
            cex_price=self._cex_mid,
            dex_price=self._dex_price,
            spread_bps=round(gross_spread_bps, 4),
            net_spread_bps=round(net_spread_bps, 4),
            estimated_profit_usd=round(estimated_profit_usd, 6),
            position_size_usd=self.position_size_usd,
            detected_at_ms=now_ms,
        )

        logger.info(
            "opportunity_detected",
            type=direction.value,
            cex=self._cex_mid,
            dex=self._dex_price,
            net_bps=round(net_spread_bps, 2),
            profit_usd=round(estimated_profit_usd, 4),
        )
        return opp

    @staticmethod
    def _calculate_spread_bps(cex_price: float, dex_price: float) -> float:
        """Calculate absolute spread in basis points."""
        return abs(cex_price - dex_price) / cex_price * 10_000

    @staticmethod
    def _determine_direction(cex_price: float, dex_price: float) -> OpportunityType:
        """Determine arb direction from price relationship."""
        if dex_price < cex_price:
            return OpportunityType.CEX_DEX_ARB_BUY   # DEX is cheap, buy there
        return OpportunityType.CEX_DEX_ARB_SELL       # DEX is expensive, sell there
```

---

## Wiring Your Detector Into the Pipeline

Once written, you register your detector in the pipeline config:

```toml
# config/free.toml
[pipeline.paper]
ingest = ["HeliusWSAdapter", "BinanceWSAdapter"]
simulator = "RPCSimulator"
sink = "PaperTradeSink"

[strategy]
class = "mev_kit.strategies.spread_tracker.SpreadTracker"

[strategy.params]
pool_address = "8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ"
cex_symbol = "SOLUSDC"
min_spread_bps = 50.0
position_size_usd = 100.0
fee_bps = 30
cooldown_ms = 2000
```

Or, for direct use in a script:

```python
# examples/paper_trade_spread_tracker.py
import asyncio
from mev_kit.pipeline.runner import PipelineRunner
from mev_kit.strategies.spread_tracker import SpreadTracker
from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
from mev_kit.adapters.sinks.paper_trade import PaperTradeSink

async def main() -> None:
    detector = SpreadTracker(
        pool_address="8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ",
        cex_symbol="SOLUSDC",
        min_spread_bps=50.0,
        position_size_usd=100.0,
    )

    runner = PipelineRunner(
        ingest_adapters=[
            HeliusWSAdapter(pool_addresses=["8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ"]),
            BinanceWSAdapter(symbols=["SOLUSDC"]),
        ],
        detector=detector,
        simulator=RPCSimulator(),
        sink=PaperTradeSink(db_path="paper_results.db"),
    )

    await runner.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Writing Tests

Tests for detectors live in `tests/unit/`. Use `pytest-asyncio` for async tests and mock the `StateUpdate` inputs directly — no external connections needed.

```python
# tests/unit/test_spread_tracker.py
import pytest
from mev_kit.models.opportunity import OpportunityType
from mev_kit.models.state import PoolState, PriceUpdate
from mev_kit.strategies.spread_tracker import SpreadTracker

POOL_ADDRESS = "8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ"

@pytest.fixture
def detector() -> SpreadTracker:
    return SpreadTracker(
        pool_address=POOL_ADDRESS,
        cex_symbol="SOLUSDC",
        min_spread_bps=20.0,
        position_size_usd=500.0,
        fee_bps=30,
        cooldown_ms=0,  # disable cooldown in tests
    )


@pytest.mark.asyncio
async def test_no_opportunity_with_one_side_only(detector: SpreadTracker) -> None:
    """Detector should not emit until both CEX and DEX prices are available."""
    price_update = PriceUpdate(
        source="binance", symbol="SOLUSDC",
        bid=180.40, ask=180.60, timestamp_ms=1000,
    )
    result = await detector.process(price_update)
    assert result is None


@pytest.mark.asyncio
async def test_no_opportunity_below_threshold(detector: SpreadTracker) -> None:
    """Detector should not emit when net spread is below min_spread_bps."""
    # Give CEX price: mid = 180.50
    await detector.process(PriceUpdate(
        source="binance", symbol="SOLUSDC",
        bid=180.40, ask=180.60, timestamp_ms=1000,
    ))
    # Give DEX price close to CEX (spread ~10bps gross, -20bps net after 30bps fee)
    pool_state = PoolState(
        pool_address=POOL_ADDRESS,
        base_mint="So11111111111111111111111111111111111111112",
        quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        reserve_base=1_000_000.0,
        reserve_quote=180_518_000.0,  # ~180.518 per SOL, ~1bps from CEX
        fee_bps=30,
        timestamp_ms=1001,
    )
    result = await detector.process(pool_state)
    assert result is None


@pytest.mark.asyncio
async def test_opportunity_emitted_buy_dex(detector: SpreadTracker) -> None:
    """Detector should emit BUY_DEX opportunity when DEX is sufficiently cheap."""
    # CEX mid: 180.50
    await detector.process(PriceUpdate(
        source="binance", symbol="SOLUSDC",
        bid=180.40, ask=180.60, timestamp_ms=1000,
    ))
    # DEX price: 180.00 (spread = 50/180.50*10000 ≈ 277 bps; net = 247 bps)
    result = await detector.process(PoolState(
        pool_address=POOL_ADDRESS,
        base_mint="So11111111111111111111111111111111111111112",
        quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        reserve_base=1_000_000.0,
        reserve_quote=180_000_000.0,
        fee_bps=30,
        timestamp_ms=1001,
    ))
    assert result is not None
    assert result.opportunity_type == OpportunityType.CEX_DEX_ARB_BUY
    assert result.net_spread_bps > 20.0
    assert result.estimated_profit_usd > 0


@pytest.mark.asyncio
async def test_cooldown_suppresses_duplicate(detector: SpreadTracker) -> None:
    """Two identical updates within cooldown window should only emit once."""
    detector.cooldown_ms = 60_000  # 1 minute cooldown

    cex = PriceUpdate(
        source="binance", symbol="SOLUSDC",
        bid=180.40, ask=180.60, timestamp_ms=1000,
    )
    pool = PoolState(
        pool_address=POOL_ADDRESS,
        base_mint="So11111111111111111111111111111111111111112",
        quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        reserve_base=1_000_000.0,
        reserve_quote=180_000_000.0,
        fee_bps=30,
        timestamp_ms=1001,
    )

    await detector.process(cex)
    first = await detector.process(pool)
    second = await detector.process(pool)  # within cooldown

    assert first is not None
    assert second is None
```

Run tests:

```bash
pytest tests/unit/test_spread_tracker.py -v
```

---

## Common Patterns and Pitfalls

### Pattern: Staleness Checking

If you haven't received a DEX update in 5 seconds, your cached pool price is stale. Check timestamps before emitting:

```python
MAX_STALENESS_MS = 5_000

def _maybe_emit_opportunity(self) -> Opportunity | None:
    now_ms = int(time.time() * 1_000)
    if now_ms - self._last_pool_update_ms > MAX_STALENESS_MS:
        logger.warning("pool_state_stale", age_ms=now_ms - self._last_pool_update_ms)
        return None
    # ... rest of logic
```

### Pattern: Multi-Pool Tracking

If your strategy watches multiple pools, store state per pool address:

```python
self._pool_states: dict[str, PoolState] = {}

async def _handle_pool_state(self, update: PoolState) -> Opportunity | None:
    self._pool_states[update.pool_address] = update
    # Find the best opportunity across all pools
    return self._best_opportunity()
```

### Pitfall: Blocking the Event Loop

Never perform synchronous I/O (file reads, HTTP calls, `time.sleep`) inside `process`. The pipeline calls `process` for every incoming update. Any blocking call here stalls the entire pipeline.

```python
# WRONG - blocks the event loop
async def process(self, update: StateUpdate) -> Opportunity | None:
    response = requests.get("https://...")  # DO NOT do this

# RIGHT - use async I/O
async def process(self, update: StateUpdate) -> Opportunity | None:
    async with httpx.AsyncClient() as client:
        response = await client.get("https://...")  # OK
```

### Pitfall: Mutable State in Tests

Detectors have internal state (`_cex_mid`, `_dex_price`, etc.). Each test should use a fresh `detector` fixture to avoid state leaking between tests. The `@pytest.fixture` shown above handles this correctly — pytest creates a new instance for each test function.

---

## Further Reading

- [Guide 3: The mev-kit Pipeline](./03-pipeline.md)
- [Guide 5: Backtesting Your Strategy](./05-backtesting.md)
- Reference implementation: `src/mev_kit/strategies/cex_dex_arb.py`
- Abstract base: `src/mev_kit/strategies/base.py`
- Models: `src/mev_kit/models/opportunity.py`, `src/mev_kit/models/state.py`
