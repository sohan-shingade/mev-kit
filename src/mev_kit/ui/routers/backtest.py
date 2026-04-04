"""Backtest execution endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from mev_kit.ui.backtest_runner import BacktestRunner

router = APIRouter()
_runner = BacktestRunner()


@router.post("/start")
async def start_backtest(request: Request, body: dict[str, Any]) -> dict[str, str]:
    data_file = body.get("data_file") or body.get("data_path", "")
    # Prepend data dir if it's just a filename
    if data_file and "/" not in data_file:
        data_dir = request.app.state.data_dir
        data_file = f"{data_dir}/{data_file}" if not data_file.startswith(data_dir) else data_file
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
