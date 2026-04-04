"""Tests for Jito Bundle Sink."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mev_kit.adapters.sinks.jito_bundle import (
    JITO_TIP_ACCOUNT,
    JitoBundleSink,
    build_bundle,
    compute_tip,
)
from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    SimulationResult,
)


def _make_opportunity(estimated_profit: float = 0.05) -> Opportunity:
    return Opportunity(
        id=str(uuid.uuid4()),
        type=OpportunityType.CEX_DEX_ARB,
        direction=Direction.BUY_DEX,
        dex_price=148.0,
        reference_price=149.5,
        spread_bps=70.0,
        estimated_profit_sol=estimated_profit,
        pool_address="58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        dex="raydium",
        pair="SOL/USDC",
        slot=12345,
        amount_in_lamports=10_000_000,
        detected_at=datetime.now(UTC),
    )


def _make_simulation(gross_profit: float = 0.05, net_profit: float = 0.03) -> SimulationResult:
    return SimulationResult(
        opportunity_id="test",
        profitable=True,
        gross_profit_sol=gross_profit,
        net_profit_sol=net_profit,
    )


class TestComputeTip:
    """Tests for tip calculation logic."""

    def test_normal_tip(self) -> None:
        """Test tip calculation within bounds."""
        # 0.4 * 50M = 20M lamports
        tip = compute_tip(
            gross_profit_lamports=50_000_000,
            tip_percentage=0.4,
            min_tip=10_000,
            max_tip=5_000_000,
        )
        assert tip == 5_000_000  # Clamped to max

    def test_tip_clamped_to_min(self) -> None:
        """Test tip at minimum bound."""
        tip = compute_tip(
            gross_profit_lamports=10_000,
            tip_percentage=0.4,
            min_tip=10_000,
            max_tip=5_000_000,
        )
        # 0.4 * 10K = 4K, but min is 10K
        assert tip == 10_000

    def test_tip_clamped_to_max(self) -> None:
        """Test tip at maximum bound."""
        tip = compute_tip(
            gross_profit_lamports=100_000_000_000,  # 100 SOL
            tip_percentage=0.4,
            min_tip=10_000,
            max_tip=5_000_000,
        )
        assert tip == 5_000_000

    def test_tip_within_range(self) -> None:
        """Test tip falls between min and max."""
        tip = compute_tip(
            gross_profit_lamports=1_000_000,  # 0.001 SOL
            tip_percentage=0.4,
            min_tip=10_000,
            max_tip=5_000_000,
        )
        assert tip == 400_000  # 40% of 1M


class TestBuildBundle:
    """Tests for bundle construction."""

    def test_bundle_has_two_transactions(self) -> None:
        """Test that bundle contains swap + tip transactions."""
        opp = _make_opportunity()
        bundle = build_bundle(opp, tip_lamports=100_000)

        assert len(bundle["transactions"]) == 2

    def test_bundle_contains_tip(self) -> None:
        """Test that tip transaction references correct account."""
        import json

        opp = _make_opportunity()
        bundle = build_bundle(opp, tip_lamports=100_000)

        tip_tx = json.loads(bundle["transactions"][1])
        assert tip_tx["to"] == JITO_TIP_ACCOUNT
        assert tip_tx["amount_lamports"] == 100_000

    def test_bundle_contains_swap(self) -> None:
        """Test that swap transaction has correct pool info."""
        import json

        opp = _make_opportunity()
        bundle = build_bundle(opp, tip_lamports=100_000)

        swap_tx = json.loads(bundle["transactions"][0])
        assert swap_tx["pool_address"] == opp.pool_address
        assert swap_tx["direction"] == "buy_dex"
        assert swap_tx["amount_in_lamports"] == 10_000_000


class TestJitoBundleSink:
    """Tests for the full JitoBundleSink."""

    @pytest.mark.asyncio
    async def test_dry_run_no_http_call(self) -> None:
        """Test that dry_run mode doesn't make HTTP calls."""
        sink = JitoBundleSink({
            "dry_run": True,
            "tip_percentage": 0.4,
            "min_tip_lamports": 10_000,
            "max_tip_lamports": 5_000_000,
        })

        # Mock the client to ensure it's never called
        mock_client = AsyncMock()
        sink._client = mock_client

        opp = _make_opportunity()
        sim = _make_simulation()

        result = await sink.execute(opp, sim)

        assert result.success is True
        assert result.tip_paid_lamports > 0
        # HTTP client should NOT have been called
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_submission(self) -> None:
        """Test bundle submission with mocked HTTP response."""
        sink = JitoBundleSink({
            "dry_run": False,
            "tip_percentage": 0.4,
            "min_tip_lamports": 10_000,
            "max_tip_lamports": 5_000_000,
        })

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": "bundle-id-12345",
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        sink._client = mock_client

        opp = _make_opportunity()
        sim = _make_simulation()

        result = await sink.execute(opp, sim)

        assert result.success is True
        assert result.bundle_id == "bundle-id-12345"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_submission_failure(self) -> None:
        """Test handling of HTTP errors during submission."""
        import httpx

        sink = JitoBundleSink({"dry_run": False})

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        sink._client = mock_client

        opp = _make_opportunity()
        sim = _make_simulation()

        result = await sink.execute(opp, sim)

        assert result.success is False
        assert "Connection refused" in result.error
