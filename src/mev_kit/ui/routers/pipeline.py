"""Pipeline control and monitoring endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from mev_kit.ui.config_manager import ConfigManager
from mev_kit.ui.pipeline_manager import PipelineManager

router = APIRouter()


@router.get("/status")
async def get_status() -> dict[str, Any]:
    return PipelineManager.get().status()


@router.post("/start")
async def start_pipeline(request: Request, body: dict[str, Any]) -> dict[str, str]:
    mode = body.get("mode", "paper")
    config = body.get("config", {})

    # If a config_profile is specified, load the TOML and merge with inline overrides
    config_profile = body.get("config_profile")
    if config_profile:
        try:
            mgr = ConfigManager(request.app.state.config_dir)
            toml_config = mgr.load(config_profile)
            # Flatten nested TOML sections into a single dict for pipeline config
            merged: dict[str, Any] = {}
            for key, value in toml_config.items():
                if isinstance(value, dict):
                    merged.update(value)
                else:
                    merged[key] = value
            # Inline overrides take precedence over TOML values
            merged.update(config)
            config = merged
        except FileNotFoundError:
            return {"status": "error", "error": f"Config profile not found: {config_profile}"}

    try:
        await PipelineManager.get().start(mode, config)
        return {"status": "started", "mode": mode}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


@router.post("/stop")
async def stop_pipeline() -> dict[str, str]:
    await PipelineManager.get().stop()
    return {"status": "stopped"}


@router.post("/start-from-backtest")
async def start_from_backtest(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Start paper trading with the same strategy and params from a backtest run."""
    run_config = body.get("run_config", {})
    strategy = run_config.get("strategy", "cex_dex_arb")

    config: dict[str, Any] = {
        "mode": "paper",
        "strategy": strategy,
        "min_spread_bps": run_config.get("min_spread_bps", 15.0),
        "fee_bps": run_config.get("fee_bps", 30.0),
        "position_size_sol": run_config.get("position_size_sol", 0.01),
    }

    # Merge with any config_profile if specified
    config_profile = body.get("config_profile")
    if config_profile:
        mgr = ConfigManager(request.app.state.config_dir)
        try:
            profile = mgr.load(config_profile)
            flat: dict[str, Any] = {}
            for section in profile.values():
                if isinstance(section, dict):
                    flat.update(section)
            config.update({k: v for k, v in flat.items() if k not in config})
        except FileNotFoundError:
            pass

    try:
        await PipelineManager.get().start("paper", config)
        return {"status": "started", "mode": "paper", "strategy": strategy}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


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
                "error": status.get("error"),
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
