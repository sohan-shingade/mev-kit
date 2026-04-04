"""FastAPI server — serves the API and the React SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mev_kit.ui.routers import analysis, backtest, config, data, docs, pipeline


def create_app(config_dir: str = "config/", data_dir: str = "./data/") -> FastAPI:
    app = FastAPI(title="mev-kit", version="0.1.0")
    app.state.config_dir = config_dir
    app.state.data_dir = data_dir

    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
    app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
    app.include_router(data.router, prefix="/api/data", tags=["data"])
    app.include_router(docs.router, prefix="/api/docs", tags=["docs"])

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
