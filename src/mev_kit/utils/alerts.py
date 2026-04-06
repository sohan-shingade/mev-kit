"""Alerting system -- webhook notifications for pipeline events.

Sends notifications to configured webhook URLs (Slack, Discord, custom)
when significant pipeline events occur.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

WEBHOOK_URL = os.environ.get("MEV_KIT_WEBHOOK_URL", "")


async def send_alert(event: str, data: dict[str, Any]) -> None:
    """Send an alert to the configured webhook URL.

    Supports Slack and Discord webhook formats.
    """
    url = WEBHOOK_URL
    if not url:
        return

    message = _format_message(event, data)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Detect webhook type from URL
            if "discord" in url:
                payload = {"content": message}
            elif "slack" in url:
                payload = {"text": message}
            else:
                payload = {"event": event, "message": message, "data": data}

            await client.post(url, json=payload)
    except Exception as exc:
        logger.debug("alerts.send_failed", error=str(exc))


def _format_message(event: str, data: dict[str, Any]) -> str:
    """Format alert message for human readability."""
    if event == "pipeline.started":
        return (
            f"[mev-kit] Pipeline started: {data.get('mode', '?')} mode, "
            f"strategy: {data.get('strategy', '?')}"
        )
    elif event == "pipeline.stopped":
        return (
            f"[mev-kit] Pipeline stopped. "
            f"P&L: {data.get('total_profit_sol', 0):.4f} SOL"
        )
    elif event == "pipeline.error":
        return f"[mev-kit] Pipeline error: {data.get('error', 'unknown')}"
    elif event == "circuit_breaker":
        return (
            f"[mev-kit] Circuit breaker tripped: "
            f"{data.get('consecutive_misses', 0)} consecutive misses"
        )
    elif event == "backtest.completed":
        return (
            f"[mev-kit] Backtest complete: {data.get('total_trades', 0)} trades, "
            f"{data.get('total_profit_sol', 0):.4f} SOL, "
            f"Sharpe: {data.get('sharpe', 'N/A')}"
        )
    elif event == "sweep.completed":
        return (
            f"[mev-kit] Sweep complete: {data.get('combinations', 0)} combinations, "
            f"best Sharpe: {data.get('best_sharpe', 'N/A')}"
        )
    else:
        return f"[mev-kit] {event}: {data}"
