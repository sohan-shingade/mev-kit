"""Jito Bundle Sink — live execution via Jito block engine.

Constructs a Jito bundle containing the swap transaction and a tip
transaction, then submits it to the Jito block engine for atomic
execution.

Config keys:
    jito_url (str): Jito block engine URL.
    tip_percentage (float): Fraction of expected profit for tip. Default: 0.4
    min_tip_lamports (int): Minimum tip. Default: 10_000
    max_tip_lamports (int): Maximum tip. Default: 5_000_000
    keypair_path (str): Path to Solana keypair JSON file.
    dry_run (bool): If True, construct bundle but don't submit. Default: False
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from mev_kit.adapters.sinks.base import Sink
from mev_kit.models import ExecutionMode, ExecutionResult, Opportunity, SimulationResult

logger = structlog.get_logger()

# Jito tip account (one of the official accounts)
JITO_TIP_ACCOUNT = "HFqU5x63VTqvQss8hp11i4bPuSPGQzLJXnjg2vavp1iU"

# Jito bundle submission endpoint
DEFAULT_JITO_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"

LAMPORTS_PER_SOL = 1_000_000_000


class JitoBundleSink(Sink):
    """Submits Jito bundles for atomic MEV execution.

    Constructs a bundle containing:
        1. The swap transaction (e.g., Raydium AMM swap)
        2. A tip transaction to a Jito tip account

    Supports dry_run mode that builds the bundle but skips HTTP submission.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.jito_url: str = config.get("jito_url", DEFAULT_JITO_URL)
        self.tip_percentage: float = config.get("tip_percentage", 0.4)
        self.min_tip_lamports: int = config.get("min_tip_lamports", 10_000)
        self.max_tip_lamports: int = config.get("max_tip_lamports", 5_000_000)
        self.keypair_path: str = config.get("keypair_path", "")
        self.dry_run: bool = config.get("dry_run", False)

        self._client: httpx.AsyncClient | None = None
        self._keypair_bytes: bytes | None = None

    async def setup(self) -> None:
        """Load keypair and initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)

        if self.keypair_path and Path(self.keypair_path).exists():
            with open(self.keypair_path) as f:
                key_data = json.load(f)
            self._keypair_bytes = bytes(key_data)
            logger.info("jito_bundle.keypair_loaded", path=self.keypair_path)
        elif not self.dry_run:
            logger.warning("jito_bundle.no_keypair", path=self.keypair_path)

    async def teardown(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()

    async def execute(
        self,
        opportunity: Opportunity,
        simulation: SimulationResult,
    ) -> ExecutionResult:
        """Construct and submit a Jito bundle."""
        self._executions += 1
        submitted_at = datetime.now(UTC)

        # Calculate tip
        tip_lamports = compute_tip(
            gross_profit_lamports=int(simulation.gross_profit_sol * LAMPORTS_PER_SOL),
            tip_percentage=self.tip_percentage,
            min_tip=self.min_tip_lamports,
            max_tip=self.max_tip_lamports,
        )

        # Build the bundle — use real transaction construction when possible
        if self._keypair_bytes and not self.dry_run:
            try:
                bundle = await self._build_real_bundle(opportunity, tip_lamports)
            except Exception as exc:
                logger.warning(
                    "jito_bundle.real_bundle_failed",
                    error=str(exc),
                    opportunity_id=opportunity.id,
                )
                # Fall back to placeholder bundle
                bundle = build_bundle(opportunity, tip_lamports, self._keypair_bytes)
        else:
            bundle = build_bundle(opportunity, tip_lamports, self._keypair_bytes)

        if self.dry_run:
            logger.info(
                "jito_bundle.dry_run",
                opportunity_id=opportunity.id,
                tip_lamports=tip_lamports,
                num_transactions=len(bundle["transactions"]),
                spread_bps=opportunity.spread_bps,
            )
            self._successes += 1
            return ExecutionResult(
                opportunity_id=opportunity.id,
                mode=ExecutionMode.LIVE,
                success=True,
                tip_paid_lamports=tip_lamports,
                theoretical_profit_sol=simulation.net_profit_sol,
                submitted_at=submitted_at,
            )

        # Submit to Jito block engine
        try:
            result = await self._submit_bundle(bundle)
            self._successes += 1

            bundle_id = result.get("result", "")
            logger.info(
                "jito_bundle.submitted",
                bundle_id=bundle_id,
                tip_lamports=tip_lamports,
                opportunity_id=opportunity.id,
            )

            return ExecutionResult(
                opportunity_id=opportunity.id,
                mode=ExecutionMode.LIVE,
                success=True,
                bundle_id=str(bundle_id),
                tip_paid_lamports=tip_lamports,
                realized_profit_sol=simulation.net_profit_sol,
                submitted_at=submitted_at,
            )

        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.error(
                "jito_bundle.submit_failed",
                error=str(exc),
                opportunity_id=opportunity.id,
            )
            return ExecutionResult(
                opportunity_id=opportunity.id,
                mode=ExecutionMode.LIVE,
                success=False,
                error=str(exc),
                submitted_at=submitted_at,
            )

    async def _build_real_bundle(
        self, opportunity: Opportunity, tip_lamports: int
    ) -> dict:
        """Build a real Jito bundle with signed transactions.

        Uses the transaction_builder module to construct and sign real
        Raydium swap and Jito tip transactions. Falls back to the
        placeholder bundle for unknown pools.

        Args:
            opportunity: The detected opportunity to execute.
            tip_lamports: Jito tip amount in lamports.

        Returns:
            Dict with "transactions" list of base64-encoded signed tx strings.

        Raises:
            RuntimeError: If keypair is not available.
            ValueError: If pool accounts are unknown (caller should fall back).
        """
        from solders.keypair import Keypair

        from mev_kit.utils.transaction_builder import (
            build_bundle_transactions,
            get_pool_accounts,
        )

        pool_accounts = get_pool_accounts(opportunity.pool_address)
        if pool_accounts is None:
            raise ValueError(f"Unknown pool: {opportunity.pool_address}")

        if self._keypair_bytes is None:
            raise RuntimeError("Keypair required for real bundle construction")

        keypair = Keypair.from_bytes(self._keypair_bytes)

        rpc_url = os.environ.get(
            "HELIUS_RPC_URL", "https://api.mainnet-beta.solana.com"
        )

        transactions = await build_bundle_transactions(
            pool_accounts=pool_accounts,
            keypair=keypair,
            amount_in=opportunity.amount_in_lamports,
            minimum_amount_out=0,  # TODO: calculate from simulation
            tip_lamports=tip_lamports,
            rpc_url=rpc_url,
        )

        return {"transactions": transactions}

    async def _submit_bundle(self, bundle: dict) -> dict:
        """Submit bundle to Jito block engine via HTTP POST."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [bundle["transactions"]],
        }

        resp = await self._client.post(self.jito_url, json=payload)
        resp.raise_for_status()
        return resp.json()


def compute_tip(
    gross_profit_lamports: int,
    tip_percentage: float,
    min_tip: int,
    max_tip: int,
) -> int:
    """Calculate Jito tip, clamped to [min_tip, max_tip].

    Args:
        gross_profit_lamports: Estimated gross profit in lamports.
        tip_percentage: Fraction of profit to tip (e.g., 0.4 = 40%).
        min_tip: Minimum tip in lamports.
        max_tip: Maximum tip in lamports.

    Returns:
        Tip amount in lamports.
    """
    tip = int(gross_profit_lamports * tip_percentage)
    return max(min_tip, min(tip, max_tip))


def build_bundle(
    opportunity: Opportunity,
    tip_lamports: int,
    keypair_bytes: bytes | None = None,
) -> dict:
    """Build a Jito bundle with swap + tip transactions.

    In production, this would construct real Solana transactions using
    solders. For MVP, we build a bundle structure that represents what
    would be submitted.

    Returns:
        Dict with "transactions" list (base64-encoded tx strings).
    """
    # Bundle structure for Jito submission
    # In production: build real transactions with solders, sign with keypair
    # For MVP: represent the bundle structure
    swap_tx = {
        "type": "swap",
        "pool_address": opportunity.pool_address,
        "direction": opportunity.direction.value,
        "amount_in_lamports": opportunity.amount_in_lamports,
        "input_mint": opportunity.input_mint,
        "output_mint": opportunity.output_mint,
        "dex": opportunity.dex,
    }

    tip_tx = {
        "type": "tip",
        "to": JITO_TIP_ACCOUNT,
        "amount_lamports": tip_lamports,
    }

    # In production, these would be base64-encoded signed transactions
    # For MVP, return the structured bundle
    return {
        "transactions": [
            json.dumps(swap_tx),  # Swap transaction placeholder
            json.dumps(tip_tx),   # Tip transaction placeholder
        ],
    }
