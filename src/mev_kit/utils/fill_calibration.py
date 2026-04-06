"""Fill simulator calibration from real order book data.

Uses Tardis.dev's free first-of-month data to measure actual
spread distributions and depth profiles, then produces calibrated
parameters for the fill simulator.

No API key needed — Tardis makes the first calendar day of each
month freely accessible for all exchanges.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

# Tardis free data: first day of any month, no API key
TARDIS_URL = "https://api.tardis.dev/v1/data-feeds/binance"


async def fetch_calibration_data(
    symbol: str = "solusdt",
    date: str | None = None,
) -> dict[str, Any]:
    """Fetch real order book data from Tardis for calibration.

    Uses the first day of the current month (free, no API key).
    Returns spread and depth statistics.

    Args:
        symbol: Trading pair symbol (e.g. "solusdt").
        date: Date string "YYYY-MM-DD". If None, uses first of current month.

    Returns:
        Dict with spread/depth statistics, or an error dict on failure.
    """
    if date is None:
        # Use first of current month
        now = datetime.now(UTC)
        date = f"{now.year}-{now.month:02d}-01"

    filters = json.dumps([
        {"channel": "depthSnapshot", "symbols": [symbol]},
    ])

    spreads: list[float] = []
    bid_depths: list[float] = []
    ask_depths: list[float] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Sample every 30 minutes across the day (48 snapshots)
            for offset in range(0, 1440, 30):
                params = {
                    "from": date,
                    "offset": offset,
                    "filters": filters,
                }

                resp = await client.get(TARDIS_URL, params=params)

                if resp.status_code == 403:
                    return {
                        "error": "Tardis returned 403 — try a first-of-month date",
                        "date": date,
                    }
                if resp.status_code == 429:
                    break  # Rate limited, use what we have
                if resp.status_code != 200:
                    continue

                # Parse NDJSON
                for line in resp.text.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) < 2:
                        continue
                    try:
                        msg = json.loads(parts[1])
                        data = msg.get("data", msg)
                        bids = data.get("bids", [])[:10]
                        asks = data.get("asks", [])[:10]

                        if bids and asks:
                            best_bid = float(bids[0][0])
                            best_ask = float(asks[0][0])
                            mid = (best_bid + best_ask) / 2
                            if mid > 0:
                                spread_bps = (best_ask - best_bid) / mid * 10000
                                spreads.append(spread_bps)
                                bid_depths.append(
                                    sum(float(b[1]) for b in bids)
                                )
                                ask_depths.append(
                                    sum(float(a[1]) for a in asks)
                                )
                    except (json.JSONDecodeError, IndexError, ValueError):
                        continue

                # Small delay between requests
                await asyncio.sleep(0.5)

    except Exception as exc:
        return {"error": str(exc)}

    if not spreads:
        return {"error": "No data collected", "date": date}

    # Compute statistics
    spreads.sort()
    bid_depths.sort()
    ask_depths.sort()

    def percentile(data: list[float], p: float) -> float:
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    calibration: dict[str, Any] = {
        "date": date,
        "symbol": symbol,
        "samples": len(spreads),
        "spread": {
            "mean_bps": round(sum(spreads) / len(spreads), 2),
            "median_bps": round(percentile(spreads, 50), 2),
            "p95_bps": round(percentile(spreads, 95), 2),
            "p99_bps": round(percentile(spreads, 99), 2),
            "min_bps": round(min(spreads), 2),
            "max_bps": round(max(spreads), 2),
        },
        "depth": {
            "mean_bid_sol": round(sum(bid_depths) / len(bid_depths), 1),
            "mean_ask_sol": round(sum(ask_depths) / len(ask_depths), 1),
            "median_bid_sol": round(percentile(bid_depths, 50), 1),
            "median_ask_sol": round(percentile(ask_depths, 50), 1),
        },
    }

    return calibration


def apply_calibration_to_profiles(calibration: dict[str, Any]) -> dict[str, Any]:
    """Update FillSimulator venue profiles with calibrated data.

    Takes calibration statistics (from fetch_calibration_data) and produces
    a dict of venue overrides that can be passed to FillSimulator config.

    Args:
        calibration: Dict with "spread" and "depth" keys from calibration.

    Returns:
        Dict mapping venue names to calibrated parameter dicts.
    """
    spread = calibration.get("spread", {})
    depth = calibration.get("depth", {})

    # Calibrated Binance parameters
    avg_spread = spread.get("mean_bps", 1.0)
    avg_depth = (
        depth.get("mean_bid_sol", 100) + depth.get("mean_ask_sol", 100)
    ) / 2

    return {
        "binance_calibrated": {
            "avg_spread_bps": avg_spread,
            "book_depth_usd": avg_depth * 80,  # rough SOL price x depth
            "book_depth_sol": avg_depth,
        },
        "coinbase_calibrated": {
            # Coinbase typically ~2x wider spread, ~60% depth of Binance
            "avg_spread_bps": avg_spread * 2,
            "book_depth_usd": avg_depth * 80 * 0.6,
            "book_depth_sol": avg_depth * 0.6,
        },
    }
