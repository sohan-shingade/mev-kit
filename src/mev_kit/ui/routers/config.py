"""Config management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from mev_kit.ui.config_manager import ConfigManager

router = APIRouter()


@router.get("/profiles")
async def list_profiles(request: Request) -> list[str]:
    mgr = ConfigManager(request.app.state.config_dir)
    return mgr.list_profiles()


@router.get("")
async def load_config(request: Request, profile: str = "free") -> dict[str, Any]:
    mgr = ConfigManager(request.app.state.config_dir)
    return mgr.load(profile)


@router.put("")
async def save_config(request: Request, profile: str, body: dict[str, Any]) -> dict[str, str]:
    mgr = ConfigManager(request.app.state.config_dir)
    mgr.save(profile, body)
    return {"status": "saved", "profile": profile}


@router.get("/env")
async def env_status(request: Request) -> dict[str, bool]:
    mgr = ConfigManager(request.app.state.config_dir)
    return mgr.env_key_status()
