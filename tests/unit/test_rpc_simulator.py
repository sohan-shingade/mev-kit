"""Tests for RPC Simulator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mev_kit.adapters.simulators.rpc_simulator import (
    LAMPORTS_PER_SOL,
    RPCSimulator,
    compute_net_profit,
)
from mev_kit.models import Direction, Opportunity, OpportunityType


def _make_opportunity(estimated_profit_sol: float = 0.01) -> Opportunity:
    """Create a test opportunity."""
    return Opportunity(
        id=str(uuid.uuid4()),
        type=OpportunityType.CEX_DEX_ARB,
        direction=Direction.BUY_DEX,
        dex_price=148.0,
        reference_price=149.5,
        spread_bps=70.0,
        estimated_profit_sol=estimated_profit_sol,
        pool_address="58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        dex="raydium",
        pair="SOL/USDC",
        slot=12345,
        detected_at=datetime.now(UTC),
    )


class TestComputeNetProfit:
    """Tests for profit calculation logic."""

    def test_profitable_opportunity(self) -> None:
        """Test that a clearly profitable opportunity returns profitable=True."""
        opp = _make_opportunity(estimated_profit_sol=0.1)  # 100M lamports gross

        result = compute_net_profit(
            opportunity=opp,
            compute_units=200_000,
            priority_fee_lamports=5_000,
            tip_percentage=0.4,
            min_tip_lamports=10_000,
            max_tip_lamports=1_000_000,
            latency_ms=50.0,
        )

        assert result.profitable is True
        assert result.gross_profit_sol == 0.1
        # Tip = 0.4 * 100_000_000 = 40_000_000 lamports (clamped to max 1_000_000)
        assert result.tip_lamports == 1_000_000
        assert result.priority_fee_lamports == 5_000
        # Net = 100M - 5K - 1M = 98_995_000 lamports
        expected_net = (100_000_000 - 5_000 - 1_000_000) / LAMPORTS_PER_SOL
        assert result.net_profit_sol == pytest.approx(expected_net)

    def test_unprofitable_tiny_spread(self) -> None:
        """Test that costs exceeding profit returns profitable=False."""
        opp = _make_opportunity(estimated_profit_sol=0.000005)  # 5000 lamports

        result = compute_net_profit(
            opportunity=opp,
            compute_units=200_000,
            priority_fee_lamports=5_000,
            tip_percentage=0.4,
            min_tip_lamports=10_000,  # Min tip alone exceeds gross profit
            max_tip_lamports=1_000_000,
            latency_ms=10.0,
        )

        assert result.profitable is False
        assert result.net_profit_sol < 0

    def test_tip_clamped_to_min(self) -> None:
        """Test that tip is at least min_tip_lamports."""
        opp = _make_opportunity(estimated_profit_sol=0.0001)  # 100K lamports
        # 0.4 * 100K = 40K, but min is 10K — so tip = 40K (above min)

        result = compute_net_profit(
            opportunity=opp,
            compute_units=100_000,
            priority_fee_lamports=5_000,
            tip_percentage=0.4,
            min_tip_lamports=10_000,
            max_tip_lamports=1_000_000,
            latency_ms=5.0,
        )

        assert result.tip_lamports >= 10_000

    def test_tip_clamped_to_max(self) -> None:
        """Test that tip never exceeds max_tip_lamports."""
        opp = _make_opportunity(estimated_profit_sol=10.0)  # 10B lamports

        result = compute_net_profit(
            opportunity=opp,
            compute_units=200_000,
            priority_fee_lamports=5_000,
            tip_percentage=0.4,
            min_tip_lamports=10_000,
            max_tip_lamports=1_000_000,
            latency_ms=5.0,
        )

        assert result.tip_lamports == 1_000_000

    def test_compute_units_recorded(self) -> None:
        """Test that compute units are passed through."""
        opp = _make_opportunity()

        result = compute_net_profit(
            opportunity=opp,
            compute_units=42_000,
            priority_fee_lamports=5_000,
            tip_percentage=0.4,
            min_tip_lamports=10_000,
            max_tip_lamports=1_000_000,
            latency_ms=100.0,
        )

        assert result.compute_units == 42_000
        assert result.sim_latency_ms == 100.0


class TestRPCSimulator:
    """Tests for the full RPC simulator with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_successful_simulation(self) -> None:
        """Test that a successful RPC simulation returns a valid result."""
        simulator = RPCSimulator({"rpc_url": "https://fake-rpc.test"})
        opp = _make_opportunity(estimated_profit_sol=0.05)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {
                "value": {
                    "err": None,
                    "unitsConsumed": 150_000,
                    "logs": ["Program log: swap success"],
                },
            },
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        simulator._client = mock_client

        result = await simulator.simulate(opp)

        assert result.profitable is True
        assert result.compute_units == 150_000
        assert result.gross_profit_sol == 0.05
        assert result.sim_latency_ms > 0

    @pytest.mark.asyncio
    async def test_failed_simulation(self) -> None:
        """Test that a failed RPC simulation returns profitable=False."""
        simulator = RPCSimulator({"rpc_url": "https://fake-rpc.test"})
        opp = _make_opportunity()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "result": {
                "value": {
                    "err": {"InstructionError": [0, "Custom(6001)"]},
                    "unitsConsumed": 50_000,
                    "logs": ["Program log: insufficient funds"],
                },
            },
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        simulator._client = mock_client

        result = await simulator.simulate(opp)

        assert result.profitable is False
        assert result.sim_error is not None
        assert result.compute_units == 50_000

    @pytest.mark.asyncio
    async def test_rpc_level_error(self) -> None:
        """Test that an RPC-level error returns profitable=False."""
        simulator = RPCSimulator({"rpc_url": "https://fake-rpc.test"})
        opp = _make_opportunity()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid request"},
            "id": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        simulator._client = mock_client

        result = await simulator.simulate(opp)

        assert result.profitable is False
        assert result.sim_error is not None

    @pytest.mark.asyncio
    async def test_network_error(self) -> None:
        """Test that network errors are handled gracefully."""
        import httpx

        simulator = RPCSimulator({"rpc_url": "https://fake-rpc.test"})
        opp = _make_opportunity()

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        simulator._client = mock_client

        result = await simulator.simulate(opp)

        assert result.profitable is False
        assert "Connection refused" in result.sim_error
