"""Tests for Binance WebSocket adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from mev_kit.adapters.ingest.binance_ws import (
    BinanceWSAdapter,
    _normalize_symbol,
    parse_trade_message,
)
from mev_kit.models import Source


class TestParseTradeMessage:
    """Tests for Binance trade message parsing."""

    def test_valid_trade_message(self) -> None:
        """Test parsing a real Binance trade message format."""
        msg = {
            "e": "trade",
            "E": 1234567890,
            "s": "SOLUSDT",
            "t": 123,
            "p": "148.50",
            "q": "10.5",
            "T": 1234567890123,
            "m": True,
            "M": True,
        }

        update = parse_trade_message(msg)

        assert update is not None
        assert update.source == Source.BINANCE_WS
        assert update.price is not None
        assert update.price.price == 148.50
        assert update.price.volume == 10.5
        assert update.price.source == Source.BINANCE_WS
        assert update.price.symbol == "SOL/USDT"

    def test_price_update_timestamp(self) -> None:
        """Test that trade timestamp is correctly parsed from milliseconds."""
        msg = {
            "e": "trade",
            "E": 1700000000000,
            "s": "SOLUSDT",
            "t": 1,
            "p": "100.00",
            "q": "1.0",
            "T": 1700000000000,
        }

        update = parse_trade_message(msg)

        assert update is not None
        expected_ts = datetime.fromtimestamp(1700000000, tz=UTC)
        assert update.price.timestamp == expected_ts

    def test_missing_required_field(self) -> None:
        """Test that missing fields return None instead of crashing."""
        msg = {"e": "trade", "s": "SOLUSDT"}  # Missing p, q, T
        assert parse_trade_message(msg) is None

    def test_invalid_price(self) -> None:
        """Test that non-numeric price returns None."""
        msg = {
            "e": "trade",
            "E": 1,
            "s": "SOLUSDT",
            "t": 1,
            "p": "not_a_number",
            "q": "1.0",
            "T": 1000000,
        }
        assert parse_trade_message(msg) is None

    def test_empty_message(self) -> None:
        """Test that an empty message returns None."""
        assert parse_trade_message({}) is None


class TestNormalizeSymbol:
    """Tests for symbol normalization."""

    def test_solusdt(self) -> None:
        assert _normalize_symbol("SOLUSDT") == "SOL/USDT"

    def test_solusdc(self) -> None:
        assert _normalize_symbol("SOLUSDC") == "SOL/USDC"

    def test_btcusdt(self) -> None:
        assert _normalize_symbol("BTCUSDT") == "BTC/USDT"

    def test_lowercase_input(self) -> None:
        assert _normalize_symbol("solusdt") == "SOL/USDT"

    def test_unknown_suffix(self) -> None:
        """Test that unknown suffixes return the uppercase raw symbol."""
        assert _normalize_symbol("ABCXYZ") == "ABCXYZ"


class TestBinanceWSAdapterConfig:
    """Tests for adapter configuration."""

    def test_default_config(self) -> None:
        adapter = BinanceWSAdapter({})
        assert adapter.symbol == "solusdt"
        assert "solusdt@trade" in adapter.ws_url

    def test_custom_symbol(self) -> None:
        adapter = BinanceWSAdapter({"symbol": "btcusdt"})
        assert adapter.symbol == "btcusdt"
        assert "btcusdt@trade" in adapter.ws_url

    def test_custom_url(self) -> None:
        adapter = BinanceWSAdapter({"ws_url": "wss://custom.host/ws"})
        assert adapter.ws_url == "wss://custom.host/ws/solusdt@trade"
