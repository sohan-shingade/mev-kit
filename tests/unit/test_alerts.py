"""Tests for the alerting system (webhook notifications)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mev_kit.utils.alerts import _format_message, send_alert


class TestFormatMessage:

    def test_pipeline_started(self) -> None:
        msg = _format_message("pipeline.started", {"mode": "paper", "strategy": "cex_dex_arb"})
        assert "Pipeline started" in msg
        assert "paper" in msg
        assert "cex_dex_arb" in msg

    def test_pipeline_stopped(self) -> None:
        msg = _format_message("pipeline.stopped", {"total_profit_sol": 1.2345})
        assert "Pipeline stopped" in msg
        assert "1.2345" in msg

    def test_pipeline_error(self) -> None:
        msg = _format_message("pipeline.error", {"error": "connection lost"})
        assert "Pipeline error" in msg
        assert "connection lost" in msg

    def test_circuit_breaker(self) -> None:
        msg = _format_message("circuit_breaker", {"consecutive_misses": 5})
        assert "Circuit breaker" in msg
        assert "5" in msg

    def test_backtest_completed(self) -> None:
        msg = _format_message("backtest.completed", {
            "total_trades": 42,
            "total_profit_sol": 0.1234,
            "sharpe": 1.5,
        })
        assert "Backtest complete" in msg
        assert "42" in msg
        assert "0.1234" in msg

    def test_sweep_completed(self) -> None:
        msg = _format_message("sweep.completed", {
            "combinations": 16,
            "best_sharpe": 2.1,
        })
        assert "Sweep complete" in msg
        assert "16" in msg

    def test_unknown_event(self) -> None:
        msg = _format_message("custom.event", {"foo": "bar"})
        assert "custom.event" in msg


class TestSendAlert:

    @pytest.mark.asyncio
    async def test_no_url_does_nothing(self) -> None:
        """When no webhook URL is set, send_alert should return without error."""
        with patch("mev_kit.utils.alerts.WEBHOOK_URL", ""):
            await send_alert("test.event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_slack_webhook_format(self) -> None:
        """Slack webhooks should receive {text: ...} format."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()

        with patch("mev_kit.utils.alerts.WEBHOOK_URL", "https://hooks.slack.com/services/xxx"):
            with patch("httpx.AsyncClient", return_value=mock_client):
                await send_alert("pipeline.started", {"mode": "paper", "strategy": "arb"})

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "text" in payload

    @pytest.mark.asyncio
    async def test_discord_webhook_format(self) -> None:
        """Discord webhooks should receive {content: ...} format."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()

        with patch("mev_kit.utils.alerts.WEBHOOK_URL", "https://discord.com/api/webhooks/xxx"):
            with patch("httpx.AsyncClient", return_value=mock_client):
                await send_alert("pipeline.stopped", {"total_profit_sol": 0.5})

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "content" in payload

    @pytest.mark.asyncio
    async def test_generic_webhook_format(self) -> None:
        """Generic webhooks should receive structured {event, message, data} format."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()

        with patch("mev_kit.utils.alerts.WEBHOOK_URL", "https://myserver.com/webhook"):
            with patch("httpx.AsyncClient", return_value=mock_client):
                await send_alert("backtest.completed", {"total_trades": 10})

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "event" in payload
        assert "message" in payload
        assert "data" in payload

    @pytest.mark.asyncio
    async def test_network_error_is_swallowed(self) -> None:
        """Network errors should be logged but not raised."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

        with patch("mev_kit.utils.alerts.WEBHOOK_URL", "https://unreachable.com/hook"):
            with patch("httpx.AsyncClient", return_value=mock_client):
                # Should not raise
                await send_alert("test.event", {})
