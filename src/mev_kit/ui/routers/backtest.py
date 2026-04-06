"""Backtest execution endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from mev_kit.ui.backtest_runner import BacktestRunner
from mev_kit.ui.sweep_runner import SweepRunner

router = APIRouter()
_runner = BacktestRunner()
_sweeper = SweepRunner()


@router.post("/start")
async def start_backtest(request: Request, body: dict[str, Any]) -> dict[str, str]:
    data_file = body.get("data_file") or body.get("data_path", "")
    # Prepend data dir if it's just a filename
    if data_file and "/" not in data_file:
        data_dir = request.app.state.data_dir.rstrip("/")
        data_file = f"{data_dir}/{data_file}"
    config = body.get("config", body)  # Accept both nested and flat
    if _runner._state == "running":
        return {"status": "error", "error": "Backtest already running"}
    asyncio.create_task(_runner.run(data_path=data_file, config=config))
    return {"status": "started"}


@router.post("/stop")
async def stop_backtest() -> dict[str, str]:
    if _runner._pipeline:
        await _runner._pipeline.stop()
    _runner._state = "idle"
    return {"status": "stopped"}


@router.get("/status")
async def backtest_status() -> dict[str, Any]:
    return _runner.status()


@router.websocket("/ws")
async def backtest_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_runner.status())
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass


# ── Parameter Sweep ──


@router.post("/sweep")
async def start_sweep(request: Request, body: dict[str, Any]) -> dict[str, str]:
    """Start a parameter sweep (grid search)."""
    data_file = body.get("data_file", "")
    if data_file and "/" not in data_file:
        data_dir = request.app.state.data_dir.rstrip("/")
        data_file = f"{data_dir}/{data_file}"

    strategy = body.get("strategy", "price_momentum")
    sweep_params = body.get("sweep", {})
    base_config = body.get("config", {})

    if not sweep_params:
        return {"status": "error", "error": "No sweep parameters provided"}

    if _sweeper._state == "running":
        return {"status": "error", "error": "Sweep already running"}

    asyncio.create_task(_sweeper.run(
        data_path=data_file,
        strategy=strategy,
        sweep_params=sweep_params,
        base_config=base_config,
    ))
    return {"status": "started"}


@router.get("/sweep/status")
async def sweep_status() -> dict[str, Any]:
    """Return current sweep state and results."""
    return _sweeper.status()


# ── Walk-Forward Validation ──


@router.post("/walk-forward")
async def start_walk_forward(request: Request, body: dict[str, Any]) -> dict[str, str]:
    """Start walk-forward validation (sweep on train, validate on test)."""
    data_file = body.get("data_file", "")
    if data_file and "/" not in data_file:
        data_dir = request.app.state.data_dir.rstrip("/")
        data_file = f"{data_dir}/{data_file}"

    strategy = body.get("strategy", "price_momentum")
    sweep_params = body.get("sweep", {})
    base_config = body.get("config", {})
    train_pct = float(body.get("train_pct", 0.7))

    if _sweeper._state == "running":
        return {"status": "error", "error": "Sweep already running"}

    asyncio.create_task(_sweeper.run_walk_forward(
        data_path=data_file,
        strategy=strategy,
        sweep_params=sweep_params,
        base_config=base_config,
        train_pct=train_pct,
    ))
    return {"status": "started"}
