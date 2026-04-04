"""Unit tests for core models and CEX-DEX arb detector."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    PoolState,
    PriceUpdate,
    Source,
    StateUpdate,
)
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector


def _now() -> datetime:
    return datetime.now(UTC)


class TestModels:
    """Test that all Pydantic models validate correctly."""

    def test_pool_state_creation(self) -> None:
        pool = PoolState(
            pool_address="58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            dex="raydium",
            base_mint="So11111111111111111111111111111111111111112",
            quote_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            base_reserve=100000.0,
            quote_reserve=14800000.0,
            price=148.0,
            slot=284729103,
            timestamp=_now(),
        )
        assert pool.price == 148.0
        assert pool.dex == "raydium"

    def test_price_update_creation(self) -> None:
        price = PriceUpdate(
            symbol="SOL/USDC",
            price=148.50,
            source=Source.BINANCE_WS,
            timestamp=_now(),
        )
        assert price.price == 148.50
        assert price.source == Source.BINANCE_WS

    def test_state_update_with_pool(self) -> None:
        pool = PoolState(
            pool_address="test",
            dex="raydium",
            base_mint="SOL",
            quote_mint="USDC",
            base_reserve=100.0,
            quote_reserve=14800.0,
            price=148.0,
            slot=1000,
            timestamp=_now(),
        )
        update = StateUpdate(source=Source.HELIUS_WS, pool=pool)
        assert update.pool is not None
        assert update.price is None

    def test_state_update_with_price(self) -> None:
        price = PriceUpdate(
            symbol="SOL/USDC",
            price=148.50,
            source=Source.BINANCE_WS,
            timestamp=_now(),
        )
        update = StateUpdate(source=Source.BINANCE_WS, price=price)
        assert update.price is not None
        assert update.pool is None

    def test_opportunity_creation(self) -> None:
        opp = Opportunity(
            id="test-123",
            type=OpportunityType.CEX_DEX_ARB,
            direction=Direction.BUY_DEX,
            dex_price=148.0,
            reference_price=148.89,
            spread_bps=30.2,
            estimated_profit_sol=0.003,
            pool_address="test",
            dex="raydium",
            pair="SOL/USDC",
        )
        assert opp.spread_bps == 30.2
        assert opp.direction == Direction.BUY_DEX


def _cex_update(price: float) -> StateUpdate:
    """Helper: create a CEX price update."""
    return StateUpdate(
        source=Source.BINANCE_WS,
        price=PriceUpdate(
            symbol="SOL/USDC",
            price=price,
            source=Source.BINANCE_WS,
            timestamp=_now(),
        ),
    )


def _dex_update(price: float) -> StateUpdate:
    """Helper: create a DEX pool update."""
    return StateUpdate(
        source=Source.HELIUS_WS,
        pool=PoolState(
            pool_address="test",
            dex="raydium",
            base_mint="SOL",
            quote_mint="USDC",
            base_reserve=100.0,
            quote_reserve=price * 100,
            price=price,
            slot=1000,
            timestamp=_now(),
        ),
    )


class TestCEXDEXArbDetector:
    """Test the reference CEX-DEX arb detector."""

    @pytest.fixture
    def detector(self) -> CEXDEXArbDetector:
        return CEXDEXArbDetector({
            "min_spread_bps": 15.0,
            "fee_bps": 30.0,
            "pair": "SOL/USDC",
            "position_size_sol": 1.0,
        })

    @pytest.mark.asyncio
    async def test_no_opportunity_without_both_prices(
        self, detector: CEXDEXArbDetector
    ) -> None:
        """Should return None until both CEX and DEX prices are available."""
        result = await detector.process(_cex_update(148.50))
        assert result is None

    @pytest.mark.asyncio
    async def test_no_opportunity_below_threshold(
        self, detector: CEXDEXArbDetector
    ) -> None:
        """Spread below threshold should not trigger."""
        await detector.process(_cex_update(148.50))
        # DEX price very close to CEX (~10 bps gross, below 30 bps fee)
        result = await detector.process(_dex_update(148.35))
        assert result is None

    @pytest.mark.asyncio
    async def test_detects_opportunity_above_threshold(
        self, detector: CEXDEXArbDetector
    ) -> None:
        """Large spread should trigger an opportunity."""
        await detector.process(_cex_update(149.50))
        # DEX at 148.00 — ~100 bps gross, ~70 bps net after 30 bps fee
        result = await detector.process(_dex_update(148.00))
        assert result is not None
        assert result.type == OpportunityType.CEX_DEX_ARB
        assert result.direction == Direction.BUY_DEX
        assert result.spread_bps > 15.0

    @pytest.mark.asyncio
    async def test_direction_sell_dex(
        self, detector: CEXDEXArbDetector
    ) -> None:
        """When DEX is more expensive than CEX, direction should be SELL_DEX."""
        await detector.process(_cex_update(148.00))
        result = await detector.process(_dex_update(149.50))
        assert result is not None
        assert result.direction == Direction.SELL_DEX

    @pytest.mark.asyncio
    async def test_opportunities_counter_increments(
        self, detector: CEXDEXArbDetector
    ) -> None:
        """Detector should track how many opportunities it has found."""
        assert detector.opportunities_detected == 0
        await detector.process(_cex_update(150.00))
        await detector.process(_dex_update(148.00))
        assert detector.opportunities_detected == 1
