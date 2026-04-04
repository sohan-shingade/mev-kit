"""Fetch historical Binance kline (candle) data via REST API.

Downloads 1-second candles from Binance and saves as Parquet.
No API key needed — uses the public API.

Usage:
    python scripts/fetch_binance_history.py --symbol SOLUSDT --interval 1s --days 1 --output ./data/
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx
import polars as pl
import structlog

logger = structlog.get_logger()

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000  # Binance max per request


async def fetch_klines(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    start_time: int | None = None,
    limit: int = MAX_LIMIT,
) -> list[dict]:
    """Fetch klines from Binance REST API."""
    params: dict = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = start_time

    try:
        resp = await client.get(BINANCE_KLINES_URL, params=params)
        resp.raise_for_status()
        raw = resp.json()

        rows = []
        for candle in raw:
            rows.append({
                "symbol": f"{symbol[:3]}/{symbol[3:]}".upper(),
                "price": float(candle[4]),  # close price
                "volume": float(candle[5]),  # volume
                "timestamp": datetime.fromtimestamp(
                    candle[0] / 1000, tz=timezone.utc
                ),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
            })
        return rows

    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        logger.warning("fetch_binance.error", error=str(exc))
        return []


async def run_fetcher(
    symbol: str,
    interval: str,
    days: int,
    output_dir: str,
) -> None:
    """Fetch historical klines in batches and save to Parquet."""
    all_rows: list[dict] = []
    # Estimate total candles needed
    seconds_per_interval = _interval_to_seconds(interval)
    total_candles = (days * 86400) // seconds_per_interval
    batches = (total_candles + MAX_LIMIT - 1) // MAX_LIMIT

    click.echo(f"Fetching {symbol} {interval} candles for {days} days (~{total_candles} candles)")

    start_time: int | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for batch in range(batches):
            rows = await fetch_klines(client, symbol, interval, start_time)
            if not rows:
                click.echo(f"No more data at batch {batch + 1}")
                break

            all_rows.extend(rows)
            # Next batch starts after last candle
            last_ts = rows[-1]["timestamp"]
            start_time = int(last_ts.timestamp() * 1000) + 1

            click.echo(f"Batch {batch + 1}/{batches}: {len(rows)} candles (total: {len(all_rows)})")

            # Rate limit: max 1200 requests/min
            if batch < batches - 1:
                await asyncio.sleep(0.1)

    if not all_rows:
        click.echo("No data fetched.")
        return

    df = pl.DataFrame(all_rows)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"binance_{symbol.lower()}_{interval}_{ts}.parquet"
    output_path = os.path.join(output_dir, filename)
    df.write_parquet(output_path)

    click.echo(f"\nSaved {len(all_rows)} candles to {output_path}")


def _interval_to_seconds(interval: str) -> int:
    """Convert Binance interval string to seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = interval[-1]
    value = int(interval[:-1])
    return value * units.get(unit, 1)


@click.command()
@click.option("--symbol", default="SOLUSDT", help="Trading pair symbol")
@click.option("--interval", default="1s", help="Candle interval (1s, 1m, 1h, 1d)")
@click.option("--days", default=1, help="Number of days to fetch")
@click.option("--output", default="./data/", help="Output directory")
def main(symbol: str, interval: str, days: int, output: str) -> None:
    """Fetch historical Binance klines to Parquet."""
    asyncio.run(run_fetcher(symbol, interval, days, output))


if __name__ == "__main__":
    main()
