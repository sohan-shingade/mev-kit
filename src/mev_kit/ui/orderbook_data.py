"""Order book data fetching from Tardis.dev and Kaiko.

Fetches historical L2 order book snapshots for realistic CEX
slippage simulation in backtesting.

Tardis.dev: tick-level data, first-of-month free, Python client
Kaiko: 30-second snapshots, enterprise-only ($28K/yr)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import structlog

logger = structlog.get_logger()


def is_tardis_available() -> bool:
    """Check if Tardis API key is configured."""
    return bool(os.environ.get("TARDIS_API_KEY"))


def is_kaiko_available() -> bool:
    """Check if Kaiko API key is configured."""
    return bool(os.environ.get("KAIKO_API_KEY"))


def get_orderbook_provider() -> str | None:
    """Return the best available order book data provider."""
    if is_tardis_available():
        return "tardis"
    if is_kaiko_available():
        return "kaiko"
    return None


async def fetch_tardis_orderbook(
    exchange: str,
    symbol: str,
    date: str,
    output_dir: str,
    levels: int = 10,
) -> dict[str, Any]:
    """Fetch order book snapshots from Tardis.dev.

    Uses the HTTP API to get depthSnapshot data for a specific date.
    Returns top N levels of bids and asks at regular intervals.

    Args:
        exchange: "binance" or "coinbase"
        symbol: "solusdt" (Binance format)
        date: "2026-04-01" (YYYY-MM-DD)
        output_dir: where to save the Parquet output
        levels: number of bid/ask levels to keep
    """
    import asyncio
    import json

    api_key = os.environ.get("TARDIS_API_KEY", "")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Tardis streams one minute at a time
    # For a full day, we sample every 5 minutes (288 snapshots)
    url = f"https://api.tardis.dev/v1/data-feeds/{exchange}"

    filters = json.dumps([
        {"channel": "depthSnapshot", "symbols": [symbol.lower()]},
    ])

    rows: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Sample every 5 minutes across the day
            for offset in range(0, 1440, 5):
                params: dict[str, Any] = {
                    "from": date,
                    "offset": offset,
                    "filters": filters,
                }
                resp = await client.get(url, params=params, headers=headers)

                if resp.status_code == 429:
                    logger.warning("tardis.rate_limited", offset=offset)
                    break
                if resp.status_code == 403:
                    return {"error": "Tardis API key required (free: first day of each month)"}

                resp.raise_for_status()

                # Parse NDJSON response
                for line in resp.text.strip().split("\n"):
                    if not line.strip():
                        continue
                    # Format: "2024-03-01T00:00:00.123Z {json}"
                    parts = line.split(" ", 1)
                    if len(parts) < 2:
                        continue
                    ts_str, json_str = parts
                    try:
                        msg = json.loads(json_str)
                        data = msg.get("data", msg)
                        bids = data.get("bids", [])[:levels]
                        asks = data.get("asks", [])[:levels]

                        if bids and asks:
                            # Compute book metrics
                            best_bid = float(bids[0][0])
                            best_ask = float(asks[0][0])
                            mid = (best_bid + best_ask) / 2
                            spread_bps = (best_ask - best_bid) / mid * 10000

                            bid_depth = sum(float(b[1]) for b in bids)
                            ask_depth = sum(float(a[1]) for a in asks)

                            rows.append({
                                "timestamp": datetime.fromisoformat(
                                    ts_str.replace("Z", "+00:00")
                                ),
                                "exchange": exchange,
                                "symbol": symbol,
                                "best_bid": best_bid,
                                "best_ask": best_ask,
                                "mid_price": mid,
                                "spread_bps": round(spread_bps, 2),
                                "bid_depth": round(bid_depth, 4),
                                "ask_depth": round(ask_depth, 4),
                                "bid_levels": len(bids),
                                "ask_levels": len(asks),
                                # Store top 5 levels as JSON for slippage calculation
                                "bids_json": json.dumps(bids[:5]),
                                "asks_json": json.dumps(asks[:5]),
                            })
                    except (json.JSONDecodeError, IndexError, ValueError):
                        continue

                # Rate limit: be conservative
                await asyncio.sleep(0.5)

        if not rows:
            return {"error": "No order book data returned", "rows": 0}

        df = pl.DataFrame(rows)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filename = f"orderbook_{exchange}_{symbol}_{date.replace('-', '')}.parquet"
        df.write_parquet(str(Path(output_dir) / filename))

        return {
            "status": "completed",
            "file": filename,
            "rows": len(rows),
            "avg_spread_bps": round(float(df["spread_bps"].mean()), 2),
            "avg_bid_depth": round(float(df["bid_depth"].mean()), 2),
            "avg_ask_depth": round(float(df["ask_depth"].mean()), 2),
            "provider": "tardis",
        }

    except Exception as exc:
        return {"error": str(exc)}


async def fetch_kaiko_orderbook(
    exchange: str,
    symbol: str,
    start_date: str,
    end_date: str,
    output_dir: str,
) -> dict[str, Any]:
    """Fetch order book snapshots from Kaiko.

    Kaiko provides 30-second snapshots via REST API.
    Enterprise-only -- requires paid API key.

    Args:
        exchange: "binance" or "coinbase"
        symbol: "solusdt"
        start_date: "2026-04-01" (YYYY-MM-DD)
        end_date: "2026-04-07" (YYYY-MM-DD)
        output_dir: where to save the Parquet output
    """
    import json

    api_key = os.environ.get("KAIKO_API_KEY", "")
    if not api_key:
        return {"error": "KAIKO_API_KEY required (enterprise plan, ~$28K/yr)"}

    # Map exchange names to Kaiko codes
    exchange_map = {"binance": "binc", "coinbase": "cbse", "bybit": "bybt"}
    kaiko_exchange = exchange_map.get(exchange, exchange)

    # Map symbol: "solusdt" -> "sol-usdt"
    sym = symbol.lower()
    for quote in ("usdt", "usdc", "usd"):
        if sym.endswith(quote):
            kaiko_instrument = f"{sym[:-len(quote)]}-{quote}"
            break
    else:
        kaiko_instrument = sym

    url = (
        f"https://us.market-api.kaiko.io/v2/data/order_book_snapshots.v1"
        f"/exchanges/{kaiko_exchange}/spot/{kaiko_instrument}/snapshots/full"
    )
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}

    rows: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params: dict[str, Any] = {
                "start_time": f"{start_date}T00:00:00Z",
                "end_time": f"{end_date}T23:59:59Z",
                "page_size": 100,
                "limit_orders": 10,
                "slippage": 100000,  # $100K for slippage calc
                "slippage_ref": "mid_price",
                "sort": "asc",
            }

            while True:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                for snap in data.get("data", []):
                    bids = snap.get("bids", [])
                    asks = snap.get("asks", [])

                    if bids and asks:
                        best_bid = float(bids[0]["price"])
                        best_ask = float(asks[0]["price"])
                        mid = float(snap.get("mid_price", (best_bid + best_ask) / 2))

                        rows.append({
                            "timestamp": datetime.fromisoformat(
                                snap["poll_date"].replace("Z", "+00:00")
                            ),
                            "exchange": exchange,
                            "symbol": symbol,
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                            "mid_price": mid,
                            "spread_bps": (
                                round(float(snap.get("spread", 0)) / mid * 10000, 2)
                                if mid
                                else 0
                            ),
                            "bid_depth": round(
                                sum(float(b["amount"]) for b in bids), 4
                            ),
                            "ask_depth": round(
                                sum(float(a["amount"]) for a in asks), 4
                            ),
                            "bid_levels": len(bids),
                            "ask_levels": len(asks),
                            "bids_json": json.dumps(
                                [[b["price"], b["amount"]] for b in bids[:5]]
                            ),
                            "asks_json": json.dumps(
                                [[a["price"], a["amount"]] for a in asks[:5]]
                            ),
                        })

                token = data.get("continuation_token")
                if not token:
                    break
                params["continuation_token"] = token

        if not rows:
            return {"error": "No order book data returned", "rows": 0}

        df = pl.DataFrame(rows)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filename = f"orderbook_{exchange}_{symbol}_{start_date.replace('-', '')}.parquet"
        df.write_parquet(str(Path(output_dir) / filename))

        return {
            "status": "completed",
            "file": filename,
            "rows": len(rows),
            "avg_spread_bps": round(float(df["spread_bps"].mean()), 2),
            "provider": "kaiko",
        }

    except Exception as exc:
        return {"error": str(exc)}
