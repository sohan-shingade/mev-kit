"""Binance WebSocket adapter — free CEX price feed, no API key needed.

Connects to the Binance public WebSocket stream for trade data.
Parses each trade into a PriceUpdate and emits it as a StateUpdate.

Config keys:
    symbol (str): Trading pair symbol. Default: "solusdt"
    ws_url (str): WebSocket base URL. Default: wss://stream.binance.com:9443/ws
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.models import PriceUpdate, Source, StateUpdate

logger = structlog.get_logger()

DEFAULT_WS_URL = "wss://stream.binance.com:9443/ws"


class BinanceWSAdapter(IngestAdapter):
    """Streams real-time trade data from Binance public WebSocket.

    Connects to the <symbol>@trade stream and converts each trade
    message into a PriceUpdate. No API key required.

    Reconnects automatically with exponential backoff (1s, 2s, 4s, ... max 30s).
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.symbol: str = config.get("symbol", "solusdt")
        base_url = config.get("ws_url", DEFAULT_WS_URL)
        self.ws_url: str = f"{base_url}/{self.symbol}@trade"

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._backoff = 1.0
        self._max_backoff = 30.0

    async def connect(self) -> None:
        """Establish WebSocket connection to Binance trade stream."""
        self._running = True
        self._ws = await websockets.connect(self.ws_url)
        self._backoff = 1.0
        logger.info("binance_ws.connected", symbol=self.symbol, url=self.ws_url)

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Yield StateUpdate objects from Binance trade messages."""
        while self._running:
            try:
                async for raw_msg in self._ws:
                    if not self._running:
                        break
                    msg = json.loads(raw_msg)
                    update = parse_trade_message(msg)
                    if update is not None:
                        yield update
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                if not self._running:
                    break
                logger.warning(
                    "binance_ws.disconnected",
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
                self._ws = await websockets.connect(self.ws_url)
                self._backoff = 1.0
                logger.info("binance_ws.reconnected")
                return
            except (WebSocketException, OSError) as exc:
                logger.warning(
                    "binance_ws.reconnect_failed",
                    error=str(exc),
                    backoff=self._backoff,
                )


def parse_trade_message(msg: dict) -> StateUpdate | None:
    """Parse a Binance trade WebSocket message into a StateUpdate.

    Expected message format:
        {
            "e": "trade",
            "E": 1234567890,       # Event time (ms)
            "s": "SOLUSDT",        # Symbol
            "t": 123,              # Trade ID
            "p": "148.50",         # Price
            "q": "10.5",           # Quantity
            "T": 1234567890123,    # Trade time (ms)
            ...
        }

    Returns:
        StateUpdate with a PriceUpdate, or None if parsing fails.
    """
    try:
        price = float(msg["p"])
        quantity = float(msg["q"])
        trade_time_ms = int(msg["T"])
        symbol_raw = str(msg["s"])

        # Normalize symbol: "SOLUSDT" → "SOL/USDT"
        symbol = _normalize_symbol(symbol_raw)

        timestamp = datetime.fromtimestamp(trade_time_ms / 1000, tz=UTC)

        price_update = PriceUpdate(
            symbol=symbol,
            price=price,
            volume=quantity,
            source=Source.BINANCE_WS,
            timestamp=timestamp,
        )

        return StateUpdate(
            source=Source.BINANCE_WS,
            price=price_update,
            received_at=datetime.now(UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.debug("binance_ws.parse_error", error=str(exc))
        return None


def _normalize_symbol(raw: str) -> str:
    """Convert Binance symbol format to standard pair format.

    "SOLUSDT" → "SOL/USDT"
    "SOLUSDC" → "SOL/USDC"
    """
    raw = raw.upper()
    for quote in ("USDT", "USDC", "BUSD", "BTC", "ETH"):
        if raw.endswith(quote):
            base = raw[: -len(quote)]
            return f"{base}/{quote}"
    return raw
