"""Helius WebSocket adapter — free-tier on-chain data feed.

Subscribes to Raydium AMM pool account changes via the Helius WebSocket
RPC endpoint. Parses the raw account data layout to extract pool reserves,
then emits StateUpdate objects with PoolState.

Handles reconnection with exponential backoff. Uses the standard Solana
accountSubscribe RPC method over WebSocket.

Config keys:
    helius_api_key (str): Helius API key for authentication.
    helius_ws_url (str): WebSocket URL. Default: wss://mainnet.helius-rpc.com/?api-key=<key>
    pool_addresses (list[str]): Raydium AMM pool addresses to monitor.
    commitment (str): Commitment level. Default: "processed"
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.models import PoolState, Source, StateUpdate

logger = structlog.get_logger()

# Raydium AMM SOL/USDC pool
DEFAULT_POOL_ADDRESS = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

# Raydium AMM v4 account data layout offsets
# base_reserve (u64) at byte offset 64, quote_reserve (u64) at byte offset 72
RAYDIUM_BASE_RESERVE_OFFSET = 64
RAYDIUM_QUOTE_RESERVE_OFFSET = 72

# SOL and USDC mint addresses
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Decimals
SOL_DECIMALS = 9
USDC_DECIMALS = 6


class HeliusWSAdapter(IngestAdapter):
    """Connects to Helius WebSocket and streams Raydium pool state updates.

    Uses the accountSubscribe RPC method to watch for account data changes
    on specified Raydium AMM pool addresses. Parses the Raydium AMM v4 layout
    to extract base/quote reserves and compute price.

    Reconnects automatically with exponential backoff (1s, 2s, 4s, ... max 30s).
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.api_key: str = config.get("helius_api_key", "")
        self.ws_url: str = config.get(
            "helius_ws_url",
            f"wss://mainnet.helius-rpc.com/?api-key={self.api_key}",
        )
        self.pool_addresses: list[str] = config.get(
            "pool_addresses",
            [DEFAULT_POOL_ADDRESS],
        )
        self.commitment: str = config.get("commitment", "processed")

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscription_ids: dict[int, str] = {}  # sub_id -> pool_address
        self._request_id_to_pool: dict[int, str] = {}  # request_id -> pool_address
        self._next_request_id = 1
        self._backoff = 1.0
        self._max_backoff = 30.0

    async def connect(self) -> None:
        """Establish WebSocket connection and subscribe to pool accounts."""
        self._running = True
        await self._connect_and_subscribe()

    async def _connect_and_subscribe(self) -> None:
        """Connect to WebSocket and send accountSubscribe for each pool."""
        self._ws = await websockets.connect(self.ws_url)
        self._backoff = 1.0  # Reset backoff on successful connect

        for pool_address in self.pool_addresses:
            msg = self._build_subscribe_message(pool_address)
            await self._ws.send(json.dumps(msg))
            self._request_id_to_pool[msg["id"]] = pool_address

        logger.info(
            "helius_ws.connected",
            pools=self.pool_addresses,
            commitment=self.commitment,
        )

    def _build_subscribe_message(self, pool_address: str) -> dict:
        """Build a JSON-RPC accountSubscribe message."""
        request_id = self._next_request_id
        self._next_request_id += 1
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "accountSubscribe",
            "params": [
                pool_address,
                {
                    "encoding": "base64",
                    "commitment": self.commitment,
                },
            ],
        }

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._subscription_ids.clear()
        self._request_id_to_pool.clear()

    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Yield StateUpdate objects from Helius WebSocket account notifications."""
        while self._running:
            try:
                async for raw_msg in self._ws:
                    if not self._running:
                        break
                    msg = json.loads(raw_msg)
                    update = self._handle_message(msg)
                    if update is not None:
                        yield update
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                if not self._running:
                    break
                logger.warning(
                    "helius_ws.disconnected",
                    error=str(exc),
                    backoff=self._backoff,
                )
                await self._reconnect()

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        while self._running:
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)
            try:
                self._subscription_ids.clear()
                self._request_id_to_pool.clear()
                self._next_request_id = 1
                await self._connect_and_subscribe()
                logger.info("helius_ws.reconnected")
                return
            except (WebSocketException, OSError) as exc:
                logger.warning(
                    "helius_ws.reconnect_failed",
                    error=str(exc),
                    backoff=self._backoff,
                )

    def _handle_message(self, msg: dict) -> StateUpdate | None:
        """Parse a WebSocket message into a StateUpdate or None.

        Handles two message types:
            1. Subscription confirmations (result with subscription id)
            2. Account notifications (method == "accountNotification")
        """
        # Subscription confirmation
        if "id" in msg and "result" in msg:
            request_id = msg["id"]
            sub_id = msg["result"]
            pool_address = self._request_id_to_pool.get(request_id, "")
            if pool_address:
                self._subscription_ids[sub_id] = pool_address
                logger.debug(
                    "helius_ws.subscribed",
                    pool=pool_address,
                    subscription_id=sub_id,
                )
            return None

        # Account notification
        if msg.get("method") == "accountNotification":
            return self._parse_notification(msg)

        return None

    def _parse_notification(self, msg: dict) -> StateUpdate | None:
        """Parse an accountNotification into a StateUpdate with PoolState."""
        try:
            params = msg["params"]
            sub_id = params["subscription"]
            pool_address = self._subscription_ids.get(sub_id, "")
            if not pool_address:
                return None

            result = params["result"]
            context = result.get("context", {})
            slot = context.get("slot", 0)

            account_data = result["value"]["data"]
            # account_data is [base64_string, "base64"]
            import base64

            raw_bytes = base64.b64decode(account_data[0])

            pool_state = parse_raydium_amm_data(raw_bytes, pool_address, slot)
            if pool_state is None:
                return None

            return StateUpdate(
                source=Source.HELIUS_WS,
                pool=pool_state,
                received_at=datetime.now(UTC),
            )
        except (KeyError, IndexError, ValueError) as exc:
            logger.debug("helius_ws.parse_error", error=str(exc))
            return None


def parse_raydium_amm_data(
    data: bytes, pool_address: str, slot: int
) -> PoolState | None:
    """Parse Raydium AMM v4 account data into a PoolState.

    The Raydium AMM layout stores:
        - base_reserve as u64 little-endian at offset 64
        - quote_reserve as u64 little-endian at offset 72

    Args:
        data: Raw account data bytes.
        pool_address: The pool's on-chain address.
        slot: The Solana slot number.

    Returns:
        PoolState if parsing succeeds, None otherwise.
    """
    if len(data) < RAYDIUM_QUOTE_RESERVE_OFFSET + 8:
        return None

    base_reserve_raw = struct.unpack_from("<Q", data, RAYDIUM_BASE_RESERVE_OFFSET)[0]
    quote_reserve_raw = struct.unpack_from("<Q", data, RAYDIUM_QUOTE_RESERVE_OFFSET)[0]

    # Convert from raw lamports/micro-units to human-readable
    base_reserve = base_reserve_raw / (10**SOL_DECIMALS)
    quote_reserve = quote_reserve_raw / (10**USDC_DECIMALS)

    if base_reserve == 0:
        return None

    price = quote_reserve / base_reserve

    return PoolState(
        pool_address=pool_address,
        dex="raydium",
        base_mint=SOL_MINT,
        quote_mint=USDC_MINT,
        base_reserve=base_reserve,
        quote_reserve=quote_reserve,
        price=price,
        fee_bps=30,
        slot=slot,
        timestamp=datetime.now(UTC),
    )
