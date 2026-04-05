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
