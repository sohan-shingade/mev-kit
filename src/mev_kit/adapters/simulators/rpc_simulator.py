"""RPC Simulator — free-tier pre-execution simulation via Helius.

Builds a swap transaction for a detected opportunity, calls the
simulateTransaction RPC method, and parses the response to determine
if the trade would be profitable.

Config keys:
    rpc_url (str): Solana RPC URL. Defaults to HELIUS_RPC_URL env var.
    priority_fee_lamports (int): Priority fee to include. Default: 5000
    tip_percentage (float): Jito tip as fraction of profit. Default: 0.4
    min_tip_lamports (int): Minimum tip. Default: 10_000
    max_tip_lamports (int): Maximum tip. Default: 1_000_000
"""

from __future__ import annotations

import base64
import os
import time

import httpx
import structlog

from mev_kit.adapters.simulators.base import Simulator
from mev_kit.models import Opportunity, SimulationResult

logger = structlog.get_logger()

# Raydium AMM program ID
RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# SOL decimals for lamport conversion
SOL_DECIMALS = 9
LAMPORTS_PER_SOL = 10**SOL_DECIMALS


class RPCSimulator(Simulator):
    """Simulates opportunities via Solana simulateTransaction RPC.

    Calls the RPC endpoint to dry-run a swap transaction and determine
    profitability. Computes net profit after fees and tips.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.rpc_url: str = config.get(
            "rpc_url",
            os.environ.get("HELIUS_RPC_URL", "https://api.mainnet-beta.solana.com"),
        )
        self.priority_fee_lamports: int = config.get("priority_fee_lamports", 5000)
        self.tip_percentage: float = config.get("tip_percentage", 0.4)
        self.min_tip_lamports: int = config.get("min_tip_lamports", 10_000)
        self.max_tip_lamports: int = config.get("max_tip_lamports", 1_000_000)
        self._client: httpx.AsyncClient | None = None

    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        """Simulate a swap transaction for the given opportunity.

        Calls simulateTransaction RPC method. If the simulation succeeds,
        computes net profit after priority fee and Jito tip.

        Returns SimulationResult with profitable=False if simulation fails
        or net profit is negative.
        """
        start_ms = time.monotonic() * 1000

        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=10.0)

            sim_response = await self._call_simulate_transaction(opportunity)
            latency_ms = time.monotonic() * 1000 - start_ms

            return self._parse_simulation_result(opportunity, sim_response, latency_ms)

        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            latency_ms = time.monotonic() * 1000 - start_ms
            logger.warning(
                "rpc_simulator.error",
                error=str(exc),
                opportunity_id=opportunity.id,
            )
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                sim_error=str(exc),
                sim_latency_ms=latency_ms,
            )

    async def _call_simulate_transaction(self, opportunity: Opportunity) -> dict:
        """Call simulateTransaction RPC method with a real transaction.

        Builds a Raydium swap transaction using the transaction_builder
        module, serializes it to base64, and submits it to the RPC
        endpoint for simulation. Uses a dummy keypair since simulation
        does not require a real signer (sigVerify=False).
        """
        from mev_kit.utils.transaction_builder import (
            build_swap_transaction,
            get_pool_accounts_async,
        )
        from solders.keypair import Keypair

        # Look up pool accounts for this opportunity (with on-chain fallback)
        pool_accounts = await get_pool_accounts_async(
            opportunity.pool_address, self.rpc_url
        )
        if pool_accounts is None:
            return {
                "error": {
                    "message": (
                        f"Unknown pool: {opportunity.pool_address}. "
                        "RPC simulation requires known pool account addresses."
                    )
                }
            }

        # Build a real transaction for simulation
        # Use a dummy keypair — simulation doesn't require a real signer
        dummy_keypair = Keypair()

        try:
            tx_bytes = await build_swap_transaction(
                pool_accounts=pool_accounts,
                keypair=dummy_keypair,
                amount_in=opportunity.amount_in_lamports,
                minimum_amount_out=0,  # Accept any output for simulation
                rpc_url=self.rpc_url,
            )
            tx_base64 = base64.b64encode(tx_bytes).decode()
        except Exception as exc:
            return {"error": {"message": f"Failed to build simulation tx: {exc}"}}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "simulateTransaction",
            "params": [
                tx_base64,
                {
                    "encoding": "base64",
                    "commitment": "processed",
                    "replaceRecentBlockhash": True,
                    "sigVerify": False,
                },
            ],
        }

        response = await self._client.post(self.rpc_url, json=payload)
        response.raise_for_status()
        return response.json()

    def _parse_simulation_result(
        self, opportunity: Opportunity, response: dict, latency_ms: float
    ) -> SimulationResult:
        """Parse the RPC simulation response into a SimulationResult."""
        result = response.get("result", {})
        error = response.get("error")

        # Check for RPC-level error
        if error:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                sim_error=str(error),
                sim_latency_ms=latency_ms,
            )

        value = result.get("value", {})
        sim_err = value.get("err")

        # Check for transaction-level error
        if sim_err is not None:
            return SimulationResult(
                opportunity_id=opportunity.id,
                profitable=False,
                sim_error=str(sim_err),
                compute_units=value.get("unitsConsumed", 0),
                sim_latency_ms=latency_ms,
            )

        compute_units = value.get("unitsConsumed", 0)

        # Compute profitability
        return compute_net_profit(
            opportunity=opportunity,
            compute_units=compute_units,
            priority_fee_lamports=self.priority_fee_lamports,
            tip_percentage=self.tip_percentage,
            min_tip_lamports=self.min_tip_lamports,
            max_tip_lamports=self.max_tip_lamports,
            latency_ms=latency_ms,
        )


def compute_net_profit(
    opportunity: Opportunity,
    compute_units: int,
    priority_fee_lamports: int,
    tip_percentage: float,
    min_tip_lamports: int,
    max_tip_lamports: int,
    latency_ms: float,
) -> SimulationResult:
    """Compute net profit after all costs.

    Net profit = gross_profit - priority_fee - jito_tip

    The Jito tip is calculated as tip_percentage of gross profit,
    clamped to [min_tip_lamports, max_tip_lamports].
    """
    gross_profit_sol = opportunity.estimated_profit_sol
    gross_profit_lamports = int(gross_profit_sol * LAMPORTS_PER_SOL)

    # Calculate tip: percentage of gross profit, clamped
    tip_lamports = int(gross_profit_lamports * tip_percentage)
    tip_lamports = max(min_tip_lamports, min(tip_lamports, max_tip_lamports))

    # Net profit in lamports
    net_profit_lamports = gross_profit_lamports - priority_fee_lamports - tip_lamports
    net_profit_sol = net_profit_lamports / LAMPORTS_PER_SOL

    profitable = net_profit_lamports > 0

    return SimulationResult(
        opportunity_id=opportunity.id,
        profitable=profitable,
        gross_profit_sol=gross_profit_sol,
        net_profit_sol=net_profit_sol,
        tip_lamports=tip_lamports,
        priority_fee_lamports=priority_fee_lamports,
        compute_units=compute_units,
        sim_latency_ms=latency_ms,
    )
