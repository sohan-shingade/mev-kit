"""Tests for Helius WebSocket adapter."""

from __future__ import annotations

import base64
import struct
from unittest.mock import AsyncMock, patch

import pytest

from mev_kit.adapters.ingest.helius_ws import (
    DEFAULT_POOL_ADDRESS,
    RAYDIUM_BASE_RESERVE_OFFSET,
    RAYDIUM_QUOTE_RESERVE_OFFSET,
    HeliusWSAdapter,
    parse_raydium_amm_data,
)
from mev_kit.models import Source


def _build_account_data(base_reserve_lamports: int, quote_reserve_micro: int) -> bytes:
    """Build fake Raydium AMM account data with reserves at the correct offsets."""
    # Create enough bytes to hold the full layout
    data = bytearray(200)
    struct.pack_into("<Q", data, RAYDIUM_BASE_RESERVE_OFFSET, base_reserve_lamports)
    struct.pack_into("<Q", data, RAYDIUM_QUOTE_RESERVE_OFFSET, quote_reserve_micro)
    return bytes(data)


class TestHeliusWSAdapter:
    """Tests for HeliusWSAdapter."""

    def test_subscribe_message_format(self) -> None:
        """Test that the subscription message has correct JSON-RPC format."""
        adapter = HeliusWSAdapter({
            "helius_api_key": "test-key",
            "pool_addresses": [DEFAULT_POOL_ADDRESS],
            "commitment": "processed",
        })

        msg = adapter._build_subscribe_message(DEFAULT_POOL_ADDRESS)

        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "accountSubscribe"
        assert isinstance(msg["id"], int)
        assert msg["params"][0] == DEFAULT_POOL_ADDRESS
        assert msg["params"][1]["encoding"] == "base64"
        assert msg["params"][1]["commitment"] == "processed"

    def test_subscribe_message_unique_ids(self) -> None:
        """Test that each subscription gets a unique request ID."""
        adapter = HeliusWSAdapter({"helius_api_key": "test-key"})

        msg1 = adapter._build_subscribe_message("pool1")
        msg2 = adapter._build_subscribe_message("pool2")

        assert msg1["id"] != msg2["id"]

    def test_ws_url_construction(self) -> None:
        """Test that the WS URL is built from api_key when not explicitly set."""
        adapter = HeliusWSAdapter({"helius_api_key": "my-key"})
        assert "my-key" in adapter.ws_url

    def test_ws_url_explicit(self) -> None:
        """Test that an explicit ws_url overrides the default."""
        adapter = HeliusWSAdapter({
            "helius_api_key": "my-key",
            "helius_ws_url": "wss://custom.endpoint/ws",
        })
        assert adapter.ws_url == "wss://custom.endpoint/ws"


class TestParseRaydiumAMMData:
    """Tests for raw account data parsing into PoolState."""

    def test_valid_data(self) -> None:
        """Test parsing valid Raydium AMM data into PoolState."""
        # 1000 SOL = 1_000_000_000_000 lamports (1000 * 10^9)
        # 148500 USDC = 148_500_000_000 micro-USDC (148500 * 10^6)
        base_lamports = 1_000_000_000_000  # 1000 SOL
        quote_micro = 148_500_000_000  # 148,500 USDC

        data = _build_account_data(base_lamports, quote_micro)
        pool = parse_raydium_amm_data(data, DEFAULT_POOL_ADDRESS, slot=12345)

        assert pool is not None
        assert pool.pool_address == DEFAULT_POOL_ADDRESS
        assert pool.dex == "raydium"
        assert pool.base_reserve == pytest.approx(1000.0)
        assert pool.quote_reserve == pytest.approx(148500.0)
        assert pool.price == pytest.approx(148.5)
        assert pool.slot == 12345
        assert pool.fee_bps == 30

    def test_data_too_short(self) -> None:
        """Test that data shorter than required returns None."""
        data = bytes(50)  # Too short to contain reserves
        pool = parse_raydium_amm_data(data, DEFAULT_POOL_ADDRESS, slot=0)
        assert pool is None

    def test_zero_base_reserve(self) -> None:
        """Test that zero base reserve returns None (division by zero guard)."""
        data = _build_account_data(0, 148_500_000_000)
        pool = parse_raydium_amm_data(data, DEFAULT_POOL_ADDRESS, slot=0)
        assert pool is None


class TestHandleMessage:
    """Tests for WebSocket message handling."""

    def _make_adapter(self) -> HeliusWSAdapter:
        return HeliusWSAdapter({
            "helius_api_key": "test",
            "pool_addresses": [DEFAULT_POOL_ADDRESS],
        })

    def test_subscription_confirmation(self) -> None:
        """Test that subscription confirmations are tracked."""
        adapter = self._make_adapter()
        adapter._request_id_to_pool[1] = DEFAULT_POOL_ADDRESS

        result = adapter._handle_message({"id": 1, "result": 42})

        assert result is None  # Confirmations don't yield updates
        assert adapter._subscription_ids[42] == DEFAULT_POOL_ADDRESS

    def test_account_notification(self) -> None:
        """Test that a valid account notification parses into a StateUpdate."""
        adapter = self._make_adapter()
        adapter._subscription_ids[42] = DEFAULT_POOL_ADDRESS

        # Build account data with known reserves
        base_lamports = 500_000_000_000  # 500 SOL
        quote_micro = 74_250_000_000  # 74,250 USDC → price ≈ 148.5
        raw_data = _build_account_data(base_lamports, quote_micro)
        encoded = base64.b64encode(raw_data).decode()

        notification = {
            "jsonrpc": "2.0",
            "method": "accountNotification",
            "params": {
                "subscription": 42,
                "result": {
                    "context": {"slot": 99999},
                    "value": {
                        "data": [encoded, "base64"],
                        "lamports": 1000000,
                        "owner": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                        "executable": False,
                        "rentEpoch": 0,
                    },
                },
            },
        }

        update = adapter._handle_message(notification)

        assert update is not None
        assert update.source == Source.HELIUS_WS
        assert update.pool is not None
        assert update.pool.price == pytest.approx(148.5)
        assert update.pool.slot == 99999
        assert update.pool.pool_address == DEFAULT_POOL_ADDRESS

    def test_unknown_subscription_id(self) -> None:
        """Test that notifications for unknown subscriptions return None."""
        adapter = self._make_adapter()
        # Don't register subscription ID 42

        notification = {
            "jsonrpc": "2.0",
            "method": "accountNotification",
            "params": {
                "subscription": 42,
                "result": {
                    "context": {"slot": 1},
                    "value": {"data": ["AAAA", "base64"]},
                },
            },
        }

        assert adapter._handle_message(notification) is None

    def test_unknown_message_type(self) -> None:
        """Test that unrecognized message types are ignored."""
        adapter = self._make_adapter()
        assert adapter._handle_message({"foo": "bar"}) is None


class TestReconnection:
    """Tests for reconnection logic."""

    @pytest.mark.asyncio
    async def test_backoff_increases(self) -> None:
        """Test that backoff doubles on each failed reconnect attempt."""
        adapter = self._make_adapter()
        adapter._running = True
        original_backoff = adapter._backoff

        # Mock websockets.connect to fail twice then succeed
        call_count = 0

        async def mock_connect(url: str) -> AsyncMock:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("Connection refused")
            return AsyncMock()

        ws_patch = "mev_kit.adapters.ingest.helius_ws.websockets.connect"
        with patch(ws_patch, side_effect=mock_connect):
            with patch.object(adapter, "_connect_and_subscribe") as mock_sub:
                # First two calls raise, third succeeds
                mock_sub.side_effect = [OSError("fail"), OSError("fail"), None]

                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await adapter._reconnect()

                    # Should have slept with increasing backoff
                    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
                    assert len(sleep_calls) == 3
                    assert sleep_calls[0] == original_backoff  # 1.0
                    assert sleep_calls[1] == original_backoff * 2  # 2.0
                    assert sleep_calls[2] == original_backoff * 4  # 4.0

    @pytest.mark.asyncio
    async def test_backoff_caps_at_max(self) -> None:
        """Test that backoff never exceeds max_backoff."""
        adapter = self._make_adapter()
        adapter._running = True
        adapter._backoff = 16.0  # Near the max

        with patch.object(adapter, "_connect_and_subscribe", side_effect=[OSError("fail"), None]):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await adapter._reconnect()
                # After one failure at backoff=16, next backoff = min(32, 30) = 30
                assert adapter._backoff <= adapter._max_backoff

    def _make_adapter(self) -> HeliusWSAdapter:
        return HeliusWSAdapter({
            "helius_api_key": "test",
            "pool_addresses": [DEFAULT_POOL_ADDRESS],
        })
