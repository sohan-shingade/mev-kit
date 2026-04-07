"""Coinbase WebSocket adapter — free CEX price feed, no API key needed.

Connects to the Coinbase Advanced Trade WebSocket feed for real-time
market data. Uses the 'matches' channel which streams individual trades.

Coinbase WebSocket docs:
  https://docs.cdp.coinbase.com/advanced-trade/docs/ws-overview

Config keys:
    symbol (str): Trading pair. Default: "SOL-USD"
    ws_url (str): WebSocket URL. Default: wss://advanced-trade-ws.coinbase.com
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

DEFAULT_WS_URL = "wss://advanced-trade-ws.coinbase.com"


class CoinbaseWSAdapter(IngestAdapter):
    """Streams real-time trade data from Coinbase Advanced Trade WebSocket.

    Connects to the 'market_trades' channel and converts each trade
    into a PriceUpdate. No API key required for public market data.

    Reconnects automatically with exponential backoff (1s, 2s, 4s, ... max 30s).
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.symbol: str = config.get("symbol", "SOL-USD")
        self.ws_url: str = config.get("ws_url", DEFAULT_WS_URL)

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._backoff = 1.0
        self._max_backoff = 30.0

    async def connect(self) -> None:
        """Establish WebSocket connection and subscribe to trades."""
        self._running = True
        self._ws = await websockets.connect(self.ws_url)
        self._backoff = 1.0

        # Subscribe to market_trades channel
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": [self.symbol],
            "channel": "market_trades",
        }
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(
            "coinbase_ws.connected",
            symbol=self.symbol,
            url=self.ws_url,
        )

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                unsubscribe_msg = {
                    "type": "unsubscribe",
                    "product_ids": [self.symbol],
                    "channel": "market_trades",
                }
                await self._ws.send(json.dumps(unsubscribe_msg))
            except Exception:
                pass
            await self._ws.close()
            self._ws = None

    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Yield StateUpdate objects from Coinbase trade messages."""
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
                    "coinbase_ws.disconnected",
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

                subscribe_msg = {
                    "type": "subscribe",
                    "product_ids": [self.symbol],
                    "channel": "market_trades",
                }
                await self._ws.send(json.dumps(subscribe_msg))
                logger.info("coinbase_ws.reconnected")
                return
            except (WebSocketException, OSError) as exc:
                logger.warning(
                    "coinbase_ws.reconnect_failed",
                    error=str(exc),
                    backoff=self._backoff,
                )


def parse_trade_message(msg: dict) -> StateUpdate | None:
    """Parse a Coinbase Advanced Trade WebSocket message into a StateUpdate.

    The market_trades channel sends messages like:
        {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "trade_id": "123",
                            "product_id": "SOL-USD",
                            "price": "148.50",
                            "size": "10.5",
                            "side": "BUY",
                            "time": "2026-04-06T12:00:00.000000Z"
                        }
                    ]
                }
            ]
        }

    Returns:
        StateUpdate with a PriceUpdate, or None if not a trade message.
    """
    try:
        if msg.get("channel") != "market_trades":
            return None

        events = msg.get("events", [])
        if not events:
            return None

        # Process the most recent trade from the latest event
        for event in events:
            trades = event.get("trades", [])
            if not trades:
                continue

            trade = trades[-1]  # Most recent trade
            price = float(trade["price"])
            size = float(trade["size"])
            product_id = trade["product_id"]
            time_str = trade["time"]

            # Parse ISO timestamp
            # Coinbase sends: "2026-04-06T12:00:00.000000Z"
            timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))

            # Normalize symbol: "SOL-USD" → "SOL/USD"
            symbol = product_id.replace("-", "/")

            price_update = PriceUpdate(
                symbol=symbol,
                price=price,
                volume=size,
                source=Source.COINBASE_WS,
                timestamp=timestamp,
            )

            return StateUpdate(
                source=Source.COINBASE_WS,
                price=price_update,
                received_at=datetime.now(UTC),
            )

        return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.debug("coinbase_ws.parse_error", error=str(exc))
        return None
