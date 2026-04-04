"""Pipeline control and monitoring endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mev_kit.ui.pipeline_manager import PipelineManager

router = APIRouter()


@router.get("/status")
async def get_status() -> dict[str, Any]:
    return PipelineManager.get().status()


@router.post("/start")
async def start_pipeline(body: dict[str, Any]) -> dict[str, str]:
    mode = body.get("mode", "paper")
    config = body.get("config", {})
    try:
        await PipelineManager.get().start(mode, config)
        return {"status": "started", "mode": mode}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


@router.post("/stop")
async def stop_pipeline() -> dict[str, str]:
    await PipelineManager.get().stop()
    return {"status": "stopped"}


@router.patch("/params")
async def patch_params(body: dict[str, Any]) -> dict[str, Any]:
    try:
        PipelineManager.get().hot_reload(body)
        return {"status": "updated", "params": list(body.keys())}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


@router.websocket("/ws")
async def pipeline_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            mgr = PipelineManager.get()
            status = mgr.status()
            await websocket.send_json({
                "type": "metrics",
                "data": status.get("metrics", {}),
                "state": status["state"],
                "mode": status["mode"],
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
