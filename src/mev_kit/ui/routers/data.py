"""Data file management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from mev_kit.ui.data_manager import DataManager

router = APIRouter()


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


@router.delete("/files/{name}")
async def delete_file(request: Request, name: str) -> dict[str, str]:
    mgr = DataManager(request.app.state.data_dir)
    try:
        mgr.delete(name)
        return {"status": "deleted", "file": name}
    except FileNotFoundError:
        return {"error": f"File not found: {name}"}
