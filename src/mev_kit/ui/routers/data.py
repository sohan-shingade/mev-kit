"""Data file management endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from mev_kit.ui.data_manager import DataManager

logger = structlog.get_logger()
router = APIRouter()

# Background fetch job tracking
_fetch_jobs: dict[str, dict[str, Any]] = {}

# Token presets for Birdeye DEX price fetch
BIRDEYE_TOKEN_PRESETS = [
    {"label": "SOL/USDC", "base": "So11111111111111111111111111111111111111112", "quote": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
    {"label": "SOL/USDT", "base": "So11111111111111111111111111111111111111112", "quote": "Es9vMFrzaCERmKfreVDyFe3GHMC3dYTzJ3tEX2s8VdDg"},
    {"label": "RAY/USDC", "base": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R", "quote": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
    {"label": "BONK/SOL", "base": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "quote": "So11111111111111111111111111111111111111112"},
    {"label": "JTO/USDC", "base": "jtojtomepa8beP8AuQc6eXt5FriJwfFwwn2LwDeFkt", "quote": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
]


@router.get("/files")
async def list_files(request: Request) -> list[dict[str, Any]]:
    mgr = DataManager(request.app.state.data_dir)
    return mgr.list_files()


@router.get("/files/{name}/preview")
async def preview_file(request: Request, name: str, limit: int = 10) -> dict[str, Any]:
    mgr = DataManager(request.app.state.data_dir)
    try:
        return mgr.preview(name, limit)
    except FileNotFoundError:
        return {"error": f"File not found: {name}"}


@router.get("/files/{name}/download")
async def download_file(request: Request, name: str):
    path = Path(request.app.state.data_dir) / name
    if not path.exists():
        return {"error": f"File not found: {name}"}
    return FileResponse(str(path), filename=name, media_type="application/octet-stream")


@router.get("/files/{name}/sources")
async def detect_file_sources(request: Request, name: str) -> dict[str, Any]:
    """Analyze a Parquet file and return what data sources it contains."""
    path = Path(request.app.state.data_dir) / name
    if not path.exists():
        return {"error": f"File not found: {name}"}

    try:
        schema = pl.read_parquet_schema(str(path))
        columns = set(schema.keys()) if isinstance(schema, dict) else set(schema)
    except Exception as exc:
        return {"error": str(exc)}

    sources: list[dict[str, str]] = []

    # Check for merged dataset (has both DEX and CEX)
    if "dex_price" in columns and "cex_price" in columns:
        sources.append({"type": "dex", "venue": "Birdeye / DEX aggregated", "status": "included"})
        sources.append({"type": "cex", "venue": "Binance / CEX", "status": "included"})
        return {"sources": sources, "merged": True, "columns": sorted(columns)}

    # Check for pool/DEX data
    if "pool_address" in columns:
        venue = "Raydium pool state"
        if "birdeye" in name.lower():
            venue = "Birdeye DEX aggregated"
        sources.append({"type": "dex", "venue": venue, "status": "included"})

    # Check for OHLCV/price data
    ohlcv = {"open", "high", "low", "close"}
    if ohlcv.issubset(columns):
        venue = "Unknown CEX"
        lower = name.lower()
        if "binance" in lower:
            venue = "Binance"
        elif "coinbase" in lower:
            venue = "Coinbase"
        elif "bybit" in lower:
            venue = "Bybit"
        sources.append({"type": "cex", "venue": venue, "status": "included"})

    # Generic price data
    if "symbol" in columns and "price" in columns and not ohlcv.issubset(columns):
        sources.append({"type": "price", "venue": "Generic price feed", "status": "included"})

    return {"sources": sources, "merged": False, "columns": sorted(columns)}


@router.delete("/files/{name}")
async def delete_file(request: Request, name: str) -> dict[str, str]:
    mgr = DataManager(request.app.state.data_dir)
    try:
        mgr.delete(name)
        return {"status": "deleted", "file": name}
    except FileNotFoundError:
        return {"error": f"File not found: {name}"}


@router.post("/fetch/binance")
async def fetch_binance(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Fetch historical kline data from Binance public API (no key needed)."""
    symbol = body.get("symbol", "SOLUSDT").upper()
    interval = body.get("interval", "1m")
    days = int(body.get("days", 1))
    use_us = body.get("use_us", False)
    data_dir = request.app.state.data_dir

    job_id = f"binance_{symbol}_{datetime.now(UTC).strftime('%H%M%S')}"
    _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

    asyncio.create_task(_run_binance_fetch(job_id, symbol, interval, days, data_dir, use_us))
    return {"status": "started", "job_id": job_id}


@router.post("/fetch/historical")
async def fetch_historical(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Fetch historical pool state from Helius RPC (requires HELIUS_API_KEY)."""
    import os

    pool_address = body.get("pool_address", "")
    interval_str = body.get("interval", "5")
    duration_str = body.get("duration", "60")
    data_dir = request.app.state.data_dir

    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key:
        return {"status": "error", "error": "HELIUS_API_KEY not set"}

    if not pool_address:
        return {"status": "error", "error": "Pool address required"}

    job_id = f"helius_{datetime.now(UTC).strftime('%H%M%S')}"
    _fetch_jobs[job_id] = {"status": "running", "progress": 0}

    # Parse interval string (e.g., "1m", "5m", "1h") to seconds
    interval = _parse_duration_to_seconds(interval_str, default=60)
    # Parse duration string (e.g., "1d", "7d", "1h") to minutes
    duration = _parse_duration_to_minutes(duration_str, default=60)

    asyncio.create_task(
        _run_helius_fetch(job_id, pool_address, interval, duration, data_dir, api_key)
    )
    return {"status": "started", "job_id": job_id}


@router.get("/fetch/status")
async def fetch_status() -> dict[str, Any]:
    """Get status of all fetch jobs."""
    return _fetch_jobs


@router.post("/fetch/birdeye")
async def fetch_birdeye(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Fetch historical DEX OHLCV data from Birdeye API (requires BIRDEYE_API_KEY)."""
    import os

    base_address = body.get("base_address", "")
    quote_address = body.get("quote_address", "")
    interval = body.get("interval", "15m")
    days = int(body.get("days", 7))
    pair_label = body.get("pair_label", "")
    data_dir = request.app.state.data_dir

    api_key = os.environ.get("BIRDEYE_API_KEY", "")
    if not api_key:
        return {"status": "error", "error": "BIRDEYE_API_KEY not set"}

    if not base_address or not quote_address:
        return {"status": "error", "error": "base_address and quote_address are required"}

    job_id = f"birdeye_{datetime.now(UTC).strftime('%H%M%S')}"
    _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

    asyncio.create_task(
        _run_birdeye_fetch(job_id, base_address, quote_address, interval, days, pair_label, data_dir, api_key)
    )
    return {"status": "started", "job_id": job_id}


@router.post("/fetch/market")
async def fetch_market(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Unified market data fetch -- handles multiple venues and auto-merge."""
    market = body.get("market", {})
    venues = body.get("venues", [])
    interval = body.get("interval", "1m")
    days = int(body.get("days", 7))
    auto_merge = body.get("auto_merge", True)
    lag = body.get("lag", True)
    data_dir = request.app.state.data_dir.rstrip("/")

    job_id = f"market_{datetime.now(UTC).strftime('%H%M%S')}"
    _fetch_jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": len(venues) + (1 if auto_merge and len(venues) > 1 else 0),
        "steps": {},
    }

    asyncio.create_task(
        _run_market_fetch(job_id, market, venues, interval, days, auto_merge, lag, data_dir)
    )
    return {"status": "started", "job_id": job_id}


@router.post("/prepare")
async def prepare_data(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Merge DEX + CEX data into a time-aligned backtest dataset."""
    from mev_kit.ui.data_prep import prepare_backtest_data

    dex_file = body.get("dex_file", "")
    cex_file = body.get("cex_file", "")
    orderbook_file = body.get("orderbook_file", "")
    interval = int(body.get("interval_seconds", 60))
    lag = body.get("lag", True)

    data_dir = request.app.state.data_dir.rstrip("/")

    # Resolve paths
    dex_path = f"{data_dir}/{dex_file}" if "/" not in dex_file else dex_file
    cex_path = f"{data_dir}/{cex_file}" if "/" not in cex_file else cex_file
    ob_path: str | None = None
    if orderbook_file:
        ob_path = (
            f"{data_dir}/{orderbook_file}"
            if "/" not in orderbook_file
            else orderbook_file
        )

    # Generate output filename
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    lag_suffix = "_lagged" if lag else "_raw"
    output_name = f"backtest_merged{lag_suffix}_{ts}.parquet"
    output_path = f"{data_dir}/{output_name}"

    try:
        stats = prepare_backtest_data(
            dex_path=dex_path,
            cex_path=cex_path,
            output_path=output_path,
            interval_seconds=interval,
            lag=lag,
            orderbook_path=ob_path,
        )
        return {"status": "completed", **stats}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _run_birdeye_fetch(
    job_id: str,
    base_address: str,
    quote_address: str,
    interval: str,
    days: int,
    pair_label: str,
    data_dir: str,
    api_key: str,
    pool_address: str | None = None,
    venue_label: str | None = None,
) -> None:
    """Background task: fetch Birdeye DEX OHLCV data and save as Parquet.

    If pool_address is provided, uses /defi/ohlcv/pair for venue-specific data.
    Otherwise uses /defi/ohlcv/base_quote for aggregated data across all DEXes.
    """
    if pool_address:
        url = "https://public-api.birdeye.so/defi/ohlcv/pair"
    else:
        url = "https://public-api.birdeye.so/defi/ohlcv/base_quote"
    headers = {
        "X-API-KEY": api_key,
        "x-chain": "solana",
    }
    max_records_per_page = 1000

    # Birdeye interval string -> seconds for pagination
    interval_seconds_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1H": 3600,
        "4H": 14400,
        "1D": 86400,
    }
    secs = interval_seconds_map.get(interval, 900)

    now_ts = int(datetime.now(UTC).timestamp())
    time_from = now_ts - (days * 86400)
    time_to = now_ts

    total_expected = (days * 86400) // secs
    _fetch_jobs[job_id]["total"] = total_expected

    # Determine dex label for the saved data
    dex_label = venue_label if venue_label else "raydium"
    pool_id = pool_address if pool_address else "birdeye_aggregated"

    all_rows: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            current_from = time_from
            while current_from < time_to:
                if pool_address:
                    params: dict[str, Any] = {
                        "address": pool_address,
                        "type": interval,
                        "time_from": current_from,
                        "time_to": time_to,
                    }
                else:
                    params = {
                        "base_address": base_address,
                        "quote_address": quote_address,
                        "type": interval,
                        "time_from": current_from,
                        "time_to": time_to,
                    }

                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()

                items = data.get("data", {}).get("items", []) if isinstance(data.get("data"), dict) else []
                if not items:
                    break

                for item in items:
                    ts_val = item.get("unixTime") or item.get("time") or 0
                    close_price = float(item.get("c", item.get("close", 0)))
                    all_rows.append({
                        "pool_address": pool_id,
                        "dex": dex_label,
                        "base_mint": base_address,
                        "quote_mint": quote_address,
                        "base_reserve": 0.0,
                        "quote_reserve": 0.0,
                        "price": close_price,
                        "fee_bps": 30,
                        "slot": 0,
                        "timestamp": datetime.fromtimestamp(ts_val, tz=UTC),
                    })

                _fetch_jobs[job_id]["progress"] = len(all_rows)
                _fetch_jobs[job_id]["total"] = max(total_expected, len(all_rows))

                if len(items) < max_records_per_page:
                    break

                # Advance time_from past the last record to paginate
                last_ts = items[-1].get("unixTime") or items[-1].get("time") or current_from
                current_from = int(last_ts) + secs

                # Free tier: 1 request/second
                await asyncio.sleep(1.0)

        if all_rows:
            df = pl.DataFrame(all_rows)
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            label_part = pair_label.replace("/", "_").lower() if pair_label else "pair"
            venue_suffix = f"_{venue_label}" if venue_label else ""
            filename = f"birdeye_{label_part}{venue_suffix}_{interval}_{ts_str}.parquet"
            df.write_parquet(str(Path(data_dir) / filename))
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["file"] = filename
            _fetch_jobs[job_id]["rows"] = len(all_rows)
        else:
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["rows"] = 0

    except Exception as exc:
        logger.warning("fetch_birdeye.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)


async def _run_coinbase_fetch(
    job_id: str, symbol: str, interval: str, days: int, data_dir: str
) -> None:
    """Fetch historical candles from Coinbase Exchange API (free, no key)."""
    # Map interval to Coinbase granularity (seconds)
    granularity_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
    granularity = granularity_map.get(interval, 60)

    # Coinbase uses product_id format: SOL-USD
    # Convert from SOLUSDT-style to SOL-USD
    product_id = symbol.upper()
    if "-" not in product_id:
        # Try to split: SOLUSDT -> SOL-USDT, SOLUSD -> SOL-USD
        for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
            if product_id.endswith(quote):
                product_id = f"{product_id[:-len(quote)]}-{quote}"
                break

    url = f"https://api.exchange.coinbase.com/products/{product_id}/candles"
    max_per_request = 300
    total_candles = (days * 86400) // granularity

    _fetch_jobs[job_id]["total"] = total_candles
    all_rows: list[dict] = []

    now = int(datetime.now(UTC).timestamp())
    current_end = now
    current_start = now - (days * 86400)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while current_start < current_end:
                # Coinbase returns max 300 candles per request
                batch_end = min(current_start + (max_per_request * granularity), current_end)

                params: dict[str, Any] = {
                    "granularity": granularity,
                    "start": datetime.fromtimestamp(current_start, tz=UTC).isoformat(),
                    "end": datetime.fromtimestamp(batch_end, tz=UTC).isoformat(),
                }

                resp = await client.get(url, params=params)
                resp.raise_for_status()
                candles = resp.json()

                if not candles:
                    break

                for c in candles:
                    # Coinbase returns arrays: [timestamp, low, high, open, close, volume]
                    if isinstance(c, list):
                        ts, low, high, opn, close, vol = c[0], c[1], c[2], c[3], c[4], c[5]
                    else:
                        ts = c.get("time", 0)
                        low, high, opn, close = c["low"], c["high"], c["open"], c["close"]
                        vol = c.get("volume", 0)
                    all_rows.append({
                        "symbol": product_id,
                        "price": float(close),
                        "volume": float(vol),
                        "timestamp": datetime.fromtimestamp(int(ts), tz=UTC),
                        "open": float(opn),
                        "high": float(high),
                        "low": float(low),
                        "close": float(close),
                    })

                _fetch_jobs[job_id]["progress"] = len(all_rows)
                current_start = batch_end

                # Rate limit
                await asyncio.sleep(0.3)

        if all_rows:
            # Sort by timestamp (Coinbase returns newest-first)
            all_rows.sort(key=lambda r: r["timestamp"])
            df = pl.DataFrame(all_rows)
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"coinbase_{product_id.lower().replace('-', '_')}_{interval}_{ts_str}.parquet"
            df.write_parquet(str(Path(data_dir) / filename))
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["file"] = filename
            _fetch_jobs[job_id]["rows"] = len(all_rows)
        else:
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["rows"] = 0

    except Exception as exc:
        logger.warning("fetch_coinbase.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)


async def _run_bybit_fetch(
    job_id: str, symbol: str, interval: str, days: int, data_dir: str
) -> None:
    """Fetch historical klines from Bybit v5 API (free, no key)."""
    # Map interval to Bybit format
    interval_map = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
                    "1h": "60", "2h": "120", "4h": "240", "1d": "D"}
    bybit_interval = interval_map.get(interval, "1")

    url = "https://api.bybit.com/v5/market/kline"
    max_limit = 1000
    seconds_map = {"1": 60, "3": 180, "5": 300, "15": 900, "30": 1800,
                   "60": 3600, "120": 7200, "240": 14400, "D": 86400}
    secs = seconds_map.get(bybit_interval, 60)
    total_candles = (days * 86400) // secs

    _fetch_jobs[job_id]["total"] = total_candles
    all_rows: list[dict] = []

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_ms = now_ms - (days * 86400 * 1000)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            current_start = start_ms
            while current_start < now_ms:
                params: dict[str, Any] = {
                    "category": "spot",
                    "symbol": symbol.upper(),
                    "interval": bybit_interval,
                    "start": current_start,
                    "end": now_ms,
                    "limit": max_limit,
                }

                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

                if data.get("retCode") != 0:
                    raise Exception(f"Bybit API error: {data.get('retMsg')}")

                candles = data.get("result", {}).get("list", [])
                if not candles:
                    break

                for c in candles:
                    # c = [startTime_ms, open, high, low, close, volume, turnover]
                    all_rows.append({
                        "symbol": symbol.upper(),
                        "price": float(c[4]),  # close
                        "volume": float(c[5]),
                        "timestamp": datetime.fromtimestamp(int(c[0]) / 1000, tz=UTC),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                    })

                _fetch_jobs[job_id]["progress"] = len(all_rows)

                if len(candles) < max_limit:
                    break

                # Bybit returns newest-first, so advance past the oldest candle
                oldest_ts = min(int(c[0]) for c in candles)
                current_start = oldest_ts + (secs * 1000)

                await asyncio.sleep(0.05)  # Bybit allows 120 req/sec

        if all_rows:
            # Sort by timestamp (Bybit returns newest-first)
            all_rows.sort(key=lambda r: r["timestamp"])
            # Deduplicate
            seen: set[str] = set()
            unique: list[dict] = []
            for r in all_rows:
                key = str(r["timestamp"])
                if key not in seen:
                    seen.add(key)
                    unique.append(r)
            all_rows = unique

            df = pl.DataFrame(all_rows)
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"bybit_{symbol.lower()}_{interval}_{ts_str}.parquet"
            df.write_parquet(str(Path(data_dir) / filename))
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["file"] = filename
            _fetch_jobs[job_id]["rows"] = len(all_rows)
        else:
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["rows"] = 0

    except Exception as exc:
        logger.warning("fetch_bybit.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)


async def _run_binance_fetch(
    job_id: str, symbol: str, interval: str, days: int, data_dir: str, use_us: bool = False
) -> None:
    """Background task: fetch Binance klines and save as Parquet."""
    base = "https://api.binance.us" if use_us else "https://api.binance.com"
    url = f"{base}/api/v3/klines"
    max_limit = 1000
    seconds_map = {"1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    secs = seconds_map.get(interval, 60)
    total_candles = (days * 86400) // secs
    max_batches = (total_candles + max_limit - 1) // max_limit

    _fetch_jobs[job_id]["total"] = total_candles
    all_rows: list[dict] = []

    # Start from N days ago
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_time = now_ms - (days * 86400 * 1000)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for batch in range(max_batches):
                params: dict[str, Any] = {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": max_limit,
                    "startTime": start_time,
                    "endTime": now_ms,
                }

                resp = await client.get(url, params=params)
                resp.raise_for_status()
                raw = resp.json()

                if not raw:
                    break

                for candle in raw:
                    all_rows.append({
                        "symbol": symbol,
                        "price": float(candle[4]),
                        "volume": float(candle[5]),
                        "timestamp": datetime.fromtimestamp(candle[0] / 1000, tz=UTC),
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                    })

                _fetch_jobs[job_id]["progress"] = len(all_rows)
                _fetch_jobs[job_id]["total"] = max(total_candles, len(all_rows))

                # If we got fewer than limit, we've exhausted available data
                if len(raw) < max_limit:
                    break

                # Advance start_time past the last candle
                start_time = int(raw[-1][0]) + 1

                # Rate limit — Binance US is stricter
                await asyncio.sleep(0.3 if use_us else 0.1)

        if all_rows:
            df = pl.DataFrame(all_rows)
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"binance_{symbol.lower()}_{interval}_{ts}.parquet"
            df.write_parquet(str(Path(data_dir) / filename))
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["file"] = filename
            _fetch_jobs[job_id]["rows"] = len(all_rows)
        else:
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["rows"] = 0

    except Exception as exc:
        logger.warning("fetch_binance.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)


def _parse_duration_to_seconds(s: str, default: int = 60) -> int:
    """Parse '1m', '5m', '1h', '1d', '30' into seconds."""
    s = s.strip().lower()
    try:
        if s.endswith("s"):
            return int(s[:-1])
        if s.endswith("m"):
            return int(s[:-1]) * 60
        if s.endswith("h"):
            return int(s[:-1]) * 3600
        if s.endswith("d"):
            return int(s[:-1]) * 86400
        return int(s)  # assume seconds if no suffix
    except ValueError:
        return default


def _parse_duration_to_minutes(s: str, default: int = 60) -> int:
    """Parse '1d', '7d', '1h', '60' into minutes."""
    s = s.strip().lower()
    try:
        if s.endswith("m"):
            return int(s[:-1])
        if s.endswith("h"):
            return int(s[:-1]) * 60
        if s.endswith("d"):
            return int(s[:-1]) * 1440
        return int(s)  # assume minutes if no suffix
    except ValueError:
        return default


async def _run_helius_fetch(
    job_id: str,
    pool_address: str,
    interval: int,
    duration: int,
    data_dir: str,
    api_key: str,
) -> None:
    """Background task: fetch Helius pool states and save as Parquet."""
    import base64
    import struct

    rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
    total_fetches = (duration * 60) // interval
    rows: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for i in range(total_fetches):
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [pool_address, {"encoding": "base64", "commitment": "confirmed"}],
                }
                resp = await client.post(rpc_url, json=payload)
                resp.raise_for_status()
                data = resp.json()

                result = data.get("result", {})
                value = result.get("value")
                slot = result.get("context", {}).get("slot", 0)

                if value and value.get("data"):
                    raw_bytes = base64.b64decode(value["data"][0])
                    if len(raw_bytes) >= 80:
                        base_raw = struct.unpack_from("<Q", raw_bytes, 64)[0]
                        quote_raw = struct.unpack_from("<Q", raw_bytes, 72)[0]
                        base_reserve = base_raw / 1e9
                        quote_reserve = quote_raw / 1e6
                        price = quote_reserve / base_reserve if base_reserve > 0 else 0

                        rows.append({
                            "pool_address": pool_address,
                            "dex": "raydium",
                            "base_mint": "So11111111111111111111111111111111111111112",
                            "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                            "base_reserve": base_reserve,
                            "quote_reserve": quote_reserve,
                            "price": price,
                            "fee_bps": 30,
                            "slot": slot,
                            "timestamp": datetime.now(UTC),
                        })

                _fetch_jobs[job_id]["progress"] = i + 1
                _fetch_jobs[job_id]["total"] = total_fetches

                if i < total_fetches - 1:
                    await asyncio.sleep(interval)

        if rows:
            df = pl.DataFrame(rows)
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"raydium_{ts}.parquet"
            df.write_parquet(str(Path(data_dir) / filename))
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["file"] = filename
            _fetch_jobs[job_id]["rows"] = len(rows)
        else:
            _fetch_jobs[job_id]["status"] = "completed"
            _fetch_jobs[job_id]["rows"] = 0

    except Exception as exc:
        logger.warning("fetch_helius.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)


async def _run_market_fetch(
    job_id: str,
    market: dict[str, Any],
    venues: list[str],
    interval: str,
    days: int,
    auto_merge: bool,
    lag: bool,
    data_dir: str,
) -> None:
    """Orchestrate multi-venue fetch + merge."""
    import os

    from mev_kit.ui.data_prep import prepare_backtest_data

    label = market.get("label", "unknown").replace("/", "_").lower()
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    fetched_files: dict[str, str] = {}

    try:
        step = 0

        # Step 1: Fetch Binance (CEX)
        if "binance" in venues and market.get("binance_symbol"):
            _fetch_jobs[job_id]["steps"]["binance"] = "running"
            symbol = market["binance_symbol"]
            use_us = market.get("use_binance_us", False)

            binance_job = f"{job_id}_binance"
            _fetch_jobs[binance_job] = {"status": "running", "progress": 0, "total": 0}

            await _run_binance_fetch(binance_job, symbol, interval, days, data_dir, use_us)

            if _fetch_jobs[binance_job]["status"] == "completed":
                fetched_files["cex"] = _fetch_jobs[binance_job].get("file", "")
                _fetch_jobs[job_id]["steps"]["binance"] = "completed"
                _fetch_jobs[job_id]["steps"]["binance_rows"] = _fetch_jobs[binance_job].get("rows", 0)
            else:
                _fetch_jobs[job_id]["steps"]["binance"] = f"error: {_fetch_jobs[binance_job].get('error', 'unknown')}"

            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Coinbase
        if "coinbase" in venues and market.get("coinbase_symbol"):
            _fetch_jobs[job_id]["steps"]["coinbase"] = "running"
            coinbase_job = f"{job_id}_coinbase"
            _fetch_jobs[coinbase_job] = {"status": "running", "progress": 0, "total": 0}
            await _run_coinbase_fetch(coinbase_job, market["coinbase_symbol"], interval, days, data_dir)
            if _fetch_jobs[coinbase_job]["status"] == "completed":
                fetched_files["coinbase"] = _fetch_jobs[coinbase_job].get("file", "")
                _fetch_jobs[job_id]["steps"]["coinbase"] = "completed"
                _fetch_jobs[job_id]["steps"]["coinbase_rows"] = _fetch_jobs[coinbase_job].get("rows", 0)
            else:
                _fetch_jobs[job_id]["steps"]["coinbase"] = f"error: {_fetch_jobs[coinbase_job].get('error', 'unknown')}"
            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Bybit
        if "bybit" in venues and market.get("bybit_symbol"):
            _fetch_jobs[job_id]["steps"]["bybit"] = "running"
            bybit_job = f"{job_id}_bybit"
            _fetch_jobs[bybit_job] = {"status": "running", "progress": 0, "total": 0}
            await _run_bybit_fetch(bybit_job, market["bybit_symbol"], interval, days, data_dir)
            if _fetch_jobs[bybit_job]["status"] == "completed":
                fetched_files["bybit"] = _fetch_jobs[bybit_job].get("file", "")
                _fetch_jobs[job_id]["steps"]["bybit"] = "completed"
                _fetch_jobs[job_id]["steps"]["bybit_rows"] = _fetch_jobs[bybit_job].get("rows", 0)
            else:
                _fetch_jobs[job_id]["steps"]["bybit"] = f"error: {_fetch_jobs[bybit_job].get('error', 'unknown')}"
            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Step 2: Fetch Birdeye (DEX)
        if "birdeye" in venues and market.get("birdeye_base"):
            api_key = os.environ.get("BIRDEYE_API_KEY", "")
            if not api_key:
                _fetch_jobs[job_id]["steps"]["birdeye"] = "error: BIRDEYE_API_KEY not set"
            else:
                _fetch_jobs[job_id]["steps"]["birdeye"] = "running"

                birdeye_job = f"{job_id}_birdeye"
                _fetch_jobs[birdeye_job] = {"status": "running", "progress": 0, "total": 0}

                # Birdeye uses uppercase H/D for hour/day intervals
                birdeye_interval = interval
                if interval in ("1h", "4h"):
                    birdeye_interval = interval[:-1] + "H"
                elif interval in ("1d",):
                    birdeye_interval = interval[:-1] + "D"

                # Support venue-specific pool fetch via Birdeye /defi/ohlcv/pair
                birdeye_pool_address = market.get("birdeye_pool_address")
                birdeye_venue_label = market.get("birdeye_venue_label")

                await _run_birdeye_fetch(
                    birdeye_job,
                    market["birdeye_base"],
                    market["birdeye_quote"],
                    birdeye_interval,
                    days,
                    market.get("label", "pair"),
                    data_dir,
                    api_key,
                    pool_address=birdeye_pool_address,
                    venue_label=birdeye_venue_label,
                )

                if _fetch_jobs[birdeye_job]["status"] == "completed":
                    fetched_files["dex"] = _fetch_jobs[birdeye_job].get("file", "")
                    _fetch_jobs[job_id]["steps"]["birdeye"] = "completed"
                    _fetch_jobs[job_id]["steps"]["birdeye_rows"] = _fetch_jobs[birdeye_job].get("rows", 0)
                else:
                    _fetch_jobs[job_id]["steps"]["birdeye"] = f"error: {_fetch_jobs[birdeye_job].get('error', 'unknown')}"

            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Step 3: Fetch Helius (live poll) -- only if selected
        if "helius" in venues and market.get("helius_pool"):
            api_key = os.environ.get("HELIUS_API_KEY", "")
            if not api_key:
                _fetch_jobs[job_id]["steps"]["helius"] = "error: HELIUS_API_KEY not set"
            else:
                _fetch_jobs[job_id]["steps"]["helius"] = "running"
                helius_interval = _parse_duration_to_seconds(interval, default=60)
                helius_duration = min(days * 1440, 60)  # cap at 1 hour for live poll

                helius_job = f"{job_id}_helius"
                _fetch_jobs[helius_job] = {"status": "running", "progress": 0}

                await _run_helius_fetch(
                    helius_job,
                    market["helius_pool"],
                    helius_interval,
                    helius_duration,
                    data_dir,
                    api_key,
                )

                if _fetch_jobs[helius_job]["status"] == "completed":
                    fetched_files["helius"] = _fetch_jobs[helius_job].get("file", "")
                    _fetch_jobs[job_id]["steps"]["helius"] = "completed"
                    _fetch_jobs[job_id]["steps"]["helius_rows"] = _fetch_jobs[helius_job].get("rows", 0)
                else:
                    _fetch_jobs[job_id]["steps"]["helius"] = f"error: {_fetch_jobs[helius_job].get('error', 'unknown')}"

            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Step 4: Fetch order book data for CEX venues if Tardis/Kaiko is available
        from mev_kit.ui.orderbook_data import (
            fetch_kaiko_orderbook,
            fetch_tardis_orderbook,
            get_orderbook_provider,
        )

        ob_provider = get_orderbook_provider()
        if ob_provider and ("binance" in venues or "coinbase" in venues):
            _fetch_jobs[job_id]["steps"]["orderbook"] = f"running ({ob_provider})"
            exchange = "binance" if "binance" in venues else "coinbase"
            symbol = (
                market.get("binance_symbol", "")
                if "binance" in venues
                else market.get("coinbase_symbol", "")
            )

            if symbol:
                # Use the first day of the requested date range as the date for Tardis
                from datetime import UTC, timedelta
                start_date = (
                    datetime.now(UTC) - timedelta(days=days)
                ).strftime("%Y-%m-%d")
                end_date = datetime.now(UTC).strftime("%Y-%m-%d")

                if ob_provider == "tardis":
                    ob_result = await fetch_tardis_orderbook(
                        exchange=exchange,
                        symbol=symbol.lower(),
                        date=start_date,
                        output_dir=data_dir,
                    )
                else:  # kaiko
                    ob_result = await fetch_kaiko_orderbook(
                        exchange=exchange,
                        symbol=symbol.lower(),
                        start_date=start_date,
                        end_date=end_date,
                        output_dir=data_dir,
                    )

                if ob_result.get("status") == "completed":
                    fetched_files["orderbook"] = ob_result["file"]
                    _fetch_jobs[job_id]["steps"]["orderbook"] = (
                        f"completed ({ob_provider}, {ob_result.get('rows', 0)} rows)"
                    )
                else:
                    _fetch_jobs[job_id]["steps"]["orderbook"] = (
                        f"unavailable: {ob_result.get('error', '?')}"
                    )
                    logger.warning(
                        "fetch_market.orderbook_failed",
                        provider=ob_provider,
                        error=ob_result.get("error"),
                    )
            else:
                _fetch_jobs[job_id]["steps"]["orderbook"] = "skipped (no symbol)"

            step += 1
            _fetch_jobs[job_id]["progress"] = step

        # Step 5: Auto-merge if we have both CEX and DEX data
        # Prefer Binance, fall back to Coinbase or Bybit as CEX source
        cex_file = fetched_files.get("cex") or fetched_files.get("coinbase") or fetched_files.get("bybit")
        dex_file = fetched_files.get("dex")
        ob_file = fetched_files.get("orderbook")

        if auto_merge and cex_file and dex_file:
            _fetch_jobs[job_id]["steps"]["merge"] = "running"

            interval_secs = _parse_duration_to_seconds(interval, default=60)
            lag_suffix = "_lagged" if lag else ""
            output_name = f"backtest_{label}_{interval}{lag_suffix}_{ts}.parquet"
            output_path = f"{data_dir}/{output_name}"

            try:
                stats = prepare_backtest_data(
                    dex_path=f"{data_dir}/{dex_file}",
                    cex_path=f"{data_dir}/{cex_file}",
                    output_path=output_path,
                    interval_seconds=interval_secs,
                    lag=lag,
                    orderbook_path=f"{data_dir}/{ob_file}" if ob_file else None,
                )

                if stats.get("error"):
                    _fetch_jobs[job_id]["steps"]["merge"] = f"error: {stats['error']}"
                else:
                    _fetch_jobs[job_id]["steps"]["merge"] = "completed"
                    _fetch_jobs[job_id]["merged_file"] = output_name
                    _fetch_jobs[job_id]["merge_stats"] = stats
            except Exception as merge_exc:
                _fetch_jobs[job_id]["steps"]["merge"] = f"error: {merge_exc}"

            step += 1
            _fetch_jobs[job_id]["progress"] = step

        _fetch_jobs[job_id]["status"] = "completed"
        _fetch_jobs[job_id]["files"] = fetched_files

    except Exception as exc:
        logger.warning("fetch_market.error", error=str(exc))
        _fetch_jobs[job_id]["status"] = "error"
        _fetch_jobs[job_id]["error"] = str(exc)
