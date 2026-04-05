"""Strategy file management endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()

STRATEGIES_DIR = Path(__file__).parent.parent.parent / "strategies"
EXAMPLES_DIR = STRATEGIES_DIR / "examples"


@router.get("/files")
async def list_strategies() -> list[dict[str, Any]]:
    """List all strategy files (user + examples)."""
    files = []

    # User strategies
    for p in sorted(STRATEGIES_DIR.glob("*.py")):
        if p.name.startswith("_") or p.name == "base.py":
            continue
        files.append({
            "name": p.name,
            "path": str(p.relative_to(STRATEGIES_DIR)),
            "type": "user",
            "size": p.stat().st_size,
        })

    # Example strategies
    if EXAMPLES_DIR.exists():
        for p in sorted(EXAMPLES_DIR.glob("*.py")):
            if p.name.startswith("_"):
                continue
            files.append({
                "name": p.name,
                "path": f"examples/{p.name}",
                "type": "example",
                "size": p.stat().st_size,
            })

    return files


@router.get("/files/{path:path}")
async def read_strategy(path: str) -> dict[str, str]:
    """Read a strategy file's content."""
    file_path = STRATEGIES_DIR / path
    if not file_path.exists() or not file_path.suffix == ".py":
        return {"error": f"Strategy not found: {path}"}
    return {"path": path, "content": file_path.read_text()}


@router.put("/files/{path:path}")
async def write_strategy(path: str, body: dict[str, str]) -> dict[str, str]:
    """Write/update a strategy file."""
    # Don't allow writing to examples or base
    if path.startswith("examples/") or path == "base.py":
        return {"error": "Cannot modify example or base files"}
    file_path = STRATEGIES_DIR / path
    if not path.endswith(".py"):
        return {"error": "Strategy files must be .py"}
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body.get("content", ""))
    return {"status": "saved", "path": path}


@router.post("/validate")
async def validate_strategy(body: dict[str, str]) -> dict[str, Any]:
    """Validate strategy code by attempting to compile it."""
    code = body.get("content", "")
    try:
        compile(code, "<strategy>", "exec")
        # Check for Detector subclass
        has_detector = "Detector" in code and "class " in code
        has_process = "async def process" in code
        return {
            "valid": True,
            "has_detector_class": has_detector,
            "has_process_method": has_process,
            "warnings": [] if (has_detector and has_process) else [
                "Strategy should define a class that inherits from Detector",
                "Strategy should implement 'async def process(self, update)'",
            ][:2 if not has_detector else 1 if not has_process else 0],
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "error": f"Syntax error at line {e.lineno}: {e.msg}",
            "line": e.lineno,
            "col": e.offset,
        }


@router.get("/info/{strategy}")
async def get_strategy_info(strategy: str) -> dict[str, Any]:
    """Return strategy metadata: required sources, hyperparameters, etc."""
    from mev_kit.ui.backtest_runner import _load_detector

    try:
        detector = _load_detector(strategy, {})
        sources = [s.value for s in detector.required_sources] if detector.required_sources else []
        hyper = detector.hyperparameters() if hasattr(detector, "hyperparameters") else {}
        warmup = detector.warmup_updates if hasattr(detector, "warmup_updates") else 0

        # Categorize sources
        cex_sources = {"binance_ws"}
        dex_sources = {"helius_ws", "yellowstone_grpc", "geyser", "parquet_replay", "jupiter_api"}
        needs_cex = bool(set(sources) & cex_sources)
        needs_dex = bool(set(sources) & dex_sources)

        return {
            "name": detector.name,
            "required_sources": sources,
            "needs_cex": needs_cex,
            "needs_dex": needs_dex,
            "needs_dual_source": needs_cex and needs_dex,
            "hyperparameters": {k: {"min": v[0], "max": v[1], "step": v[2]} for k, v in hyper.items()},
            "warmup_updates": warmup,
        }
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/base")
async def get_base_class() -> dict[str, str]:
    """Return the Detector base class source for reference."""
    base_path = STRATEGIES_DIR / "base.py"
    if base_path.exists():
        return {"content": base_path.read_text()}
    return {"error": "Base class not found"}


@router.get("/template")
async def get_template() -> dict[str, str]:
    """Return a starter template for a new detector."""
    template = '''"""Custom MEV Detector — describe your strategy here.

Required data sources: Source.BINANCE_WS, Source.HELIUS_WS
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class CustomDetector(Detector):
    """Your custom MEV detector.

    Describe what this detector does, what opportunities it finds,
    and what data sources it requires.
    """

    required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.min_spread_bps: float = config.get("min_spread_bps", 20.0)
        self.position_size_sol: float = config.get("position_size_sol", 0.01)
        # Add your internal state here
        self._last_price: float | None = None

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a state update and detect opportunities.

        Args:
            update: State update from a connected data source.

        Returns:
            An Opportunity if detected, None otherwise.
        """
        # TODO: Implement your detection logic
        # Example: track prices and detect when spread exceeds threshold

        return None

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        return {
            "min_spread_bps": (5.0, 50.0, 5.0),
            "position_size_sol": (0.01, 1.0, 0.1),
        }
'''
    return {"content": template}
