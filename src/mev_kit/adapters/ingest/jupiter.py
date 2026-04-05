"""Jupiter quote adapter — real-time DEX execution price via Jupiter aggregator.

Polls the Jupiter Quote API to get the actual swap output for a given
input amount. This gives the TRUE execution price including routing,
slippage, and fees — more accurate than AMM pool state alone.

Config keys:
    api_key (str): Jupiter API key (free tier from portal.jup.ag)
    input_mint (str): Input token mint (default: SOL)
    output_mint (str): Output token mint (default: USDC)
    amount_lamports (int): Swap amount for quoting (default: 1 SOL = 1e9)
    poll_interval_ms (int): Milliseconds between polls (default: 1000)
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import structlog

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.models import PriceUpdate, Source, StateUpdate

logger = structlog.get_logger()

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_DECIMALS = 9
USDC_DECIMALS = 6


class JupiterQuoteAdapter(IngestAdapter):
    """Polls Jupiter Quote API for real-time DEX execution prices."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.api_key: str = config.get("api_key", "")
        self.input_mint: str = config.get("input_mint", SOL_MINT)
        self.output_mint: str = config.get("output_mint", USDC_MINT)
        self.amount: int = config.get("amount_lamports", 1_000_000_000)  # 1 SOL
        self.poll_interval: float = config.get("poll_interval_ms", 1000) / 1000
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._running = True
        base = "https://api.jup.ag" if self.api_key else "https://lite-api.jup.ag"
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=10.0,
            headers={"x-api-key": self.api_key} if self.api_key else {},
        )

    async def disconnect(self) -> None:
        self._running = False
        if self._client:
            await self._client.aclose()

    async def stream(self) -> AsyncIterator[StateUpdate]:
        while self._running:
            try:
                resp = await self._client.get("/swap/v1/quote", params={
                    "inputMint": self.input_mint,
                    "outputMint": self.output_mint,
                    "amount": str(self.amount),
                    "slippageBps": "50",
                })
                resp.raise_for_status()
                data = resp.json()

                out_amount = int(data.get("outAmount", 0))
                in_amount = int(data.get("inAmount", self.amount))

                # Calculate effective price: USDC per SOL
                price = (out_amount / 10**USDC_DECIMALS) / (in_amount / 10**SOL_DECIMALS)

                price_update = PriceUpdate(
                    symbol="SOL/USDC",
                    price=price,
                    volume=None,
                    source=Source.JUPITER_API,
                    timestamp=datetime.now(UTC),
                    slot=data.get("contextSlot"),
                )
                yield StateUpdate(
                    source=Source.JUPITER_API,
                    price=price_update,
                    received_at=datetime.now(UTC),
                )

            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.debug("jupiter.quote_error", error=str(exc))

            await asyncio.sleep(self.poll_interval)
