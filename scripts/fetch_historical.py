"""Fetch historical Raydium pool states via Helius RPC.

Periodically polls the pool account data and stores snapshots
as a Parquet file for backtesting.

Usage:
    python scripts/fetch_historical.py --pool 58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2 \
        --interval 5 --duration 60 --output ./data/

Requires HELIUS_API_KEY environment variable.
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx
import polars as pl
import structlog

logger = structlog.get_logger()

# Raydium AMM SOL/USDC pool
DEFAULT_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

# Layout offsets (same as helius_ws.py)
BASE_RESERVE_OFFSET = 64
QUOTE_RESERVE_OFFSET = 72
SOL_DECIMALS = 9
USDC_DECIMALS = 6


async def fetch_pool_state(
    client: httpx.AsyncClient,
    rpc_url: str,
    pool_address: str,
) -> dict | None:
    """Fetch current pool account data via getAccountInfo RPC."""
    import base64

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            pool_address,
            {"encoding": "base64", "commitment": "confirmed"},
        ],
    }

    try:
        resp = await client.post(rpc_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", {})
        context = result.get("context", {})
        slot = context.get("slot", 0)
        value = result.get("value")

        if not value or not value.get("data"):
            return None

        raw_bytes = base64.b64decode(value["data"][0])

        if len(raw_bytes) < QUOTE_RESERVE_OFFSET + 8:
            return None

        base_raw = struct.unpack_from("<Q", raw_bytes, BASE_RESERVE_OFFSET)[0]
        quote_raw = struct.unpack_from("<Q", raw_bytes, QUOTE_RESERVE_OFFSET)[0]

        base_reserve = base_raw / (10**SOL_DECIMALS)
        quote_reserve = quote_raw / (10**USDC_DECIMALS)

        if base_reserve == 0:
            return None

        price = quote_reserve / base_reserve

        return {
            "pool_address": pool_address,
            "dex": "raydium",
            "base_mint": "So11111111111111111111111111111111111111112",
            "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "base_reserve": base_reserve,
            "quote_reserve": quote_reserve,
            "price": price,
            "fee_bps": 30,
            "slot": slot,
            "timestamp": datetime.now(timezone.utc),
        }

    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("fetch_historical.error", error=str(exc))
        return None


async def run_fetcher(
    pool_address: str,
    interval: int,
    duration: int,
    output_dir: str,
) -> None:
    """Fetch pool state at regular intervals and save to Parquet."""
    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key:
        click.echo("Error: HELIUS_API_KEY environment variable required.")
        sys.exit(1)

    rpc_url = os.environ.get(
        "HELIUS_RPC_URL",
        f"https://mainnet.helius-rpc.com/?api-key={api_key}",
    )

    rows: list[dict] = []
    total_seconds = duration * 60
    fetches = total_seconds // interval

    click.echo(f"Fetching {pool_address} every {interval}s for {duration}min ({fetches} samples)")

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(fetches):
            state = await fetch_pool_state(client, rpc_url, pool_address)
            if state:
                rows.append(state)
                click.echo(
                    f"Fetched slot {state['slot']} — "
                    f"price: {state['price']:.2f} SOL/USDC "
                    f"({len(rows)}/{fetches})"
                )
            else:
                click.echo(f"Failed to fetch ({i + 1}/{fetches})")

            if i < fetches - 1:
                await asyncio.sleep(interval)

    if not rows:
        click.echo("No data fetched.")
        return

    df = pl.DataFrame(rows)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"raydium_sol_usdc_{ts}.parquet"
    output_path = os.path.join(output_dir, filename)
    df.write_parquet(output_path)

    click.echo(f"\nSaved {len(rows)} samples to {output_path}")


@click.command()
@click.option("--pool", default=DEFAULT_POOL, help="Raydium AMM pool address")
@click.option("--interval", default=5, help="Seconds between fetches")
@click.option("--duration", default=60, help="Total duration in minutes")
@click.option("--output", default="./data/", help="Output directory")
def main(pool: str, interval: int, duration: int, output: str) -> None:
    """Fetch historical Raydium pool states to Parquet."""
    asyncio.run(run_fetcher(pool, interval, duration, output))


if __name__ == "__main__":
    main()
