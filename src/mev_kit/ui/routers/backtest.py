"""Backtest execution endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mev_kit.ui.backtest_runner import BacktestRunner

router = APIRouter()
_runner = BacktestRunner()


@router.post("/start")
async def start_backtest(body: dict[str, Any]) -> dict[str, str]:
    data_path = body.get("data_path", "")
    config = body.get("config", {})
    asyncio.create_task(_runner.run(data_path=data_path, config=config))
    return {"status": "started"}


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
