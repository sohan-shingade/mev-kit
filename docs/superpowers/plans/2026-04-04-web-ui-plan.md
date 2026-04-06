# mev-kit Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a professional, data-dense web dashboard for mev-kit that provides full pipeline control, real-time monitoring, backtesting, analysis, data management, and educational content — launched via `mev-kit ui`.

**Architecture:** FastAPI backend exposes REST + WebSocket APIs, wrapping the existing mev-kit Pipeline. A React 18 + TypeScript SPA serves as the frontend, pre-built and bundled as static files served by FastAPI. PipelineManager singleton owns the running pipeline, pushes metrics over WebSocket at 1Hz, and supports hot-reloading detector params.

**Tech Stack:** Python (FastAPI, uvicorn, aiosqlite), React 18, TypeScript, Vite, Tailwind CSS, react-grid-layout, TradingView Lightweight Charts, Recharts, lucide-react

**Spec:** `docs/superpowers/specs/2026-04-04-web-ui-design.md`

---

## File Structure

### Backend (Python — `src/mev_kit/ui/`)

| File | Responsibility |
|------|---------------|
| `src/mev_kit/ui/__init__.py` | Package init |
| `src/mev_kit/ui/server.py` | FastAPI app, mounts static files, includes all routers |
| `src/mev_kit/ui/routers/pipeline.py` | REST + WebSocket for pipeline control and monitoring |
| `src/mev_kit/ui/routers/config.py` | Config TOML read/write/profiles |
| `src/mev_kit/ui/routers/backtest.py` | Backtest start/status + WebSocket progress |
| `src/mev_kit/ui/routers/analysis.py` | SQLite query endpoints for results analysis |
| `src/mev_kit/ui/routers/data.py` | Parquet file management + fetch job endpoints |
| `src/mev_kit/ui/routers/docs.py` | Guide listing and content endpoints |
| `src/mev_kit/ui/pipeline_manager.py` | Singleton managing running Pipeline instance |
| `src/mev_kit/ui/config_manager.py` | TOML read/write/validate, profile management |
| `src/mev_kit/ui/data_manager.py` | Parquet CRUD + background fetch jobs |
| `src/mev_kit/ui/backtest_runner.py` | Async backtest execution with progress |
| `src/mev_kit/ui/guides/01-mev-on-solana.md` | Guide: MEV on Solana concepts |
| `src/mev_kit/ui/guides/02-cex-dex-arb.md` | Guide: How CEX-DEX arb works |
| `src/mev_kit/ui/guides/03-pipeline.md` | Guide: The mev-kit pipeline |
| `src/mev_kit/ui/guides/04-custom-detector.md` | Guide: Writing a custom detector |
| `src/mev_kit/ui/guides/05-backtesting.md` | Guide: Backtesting your strategy |

### Backend Tests

| File | Tests |
|------|-------|
| `tests/unit/test_pipeline_manager.py` | PipelineManager start/stop/status/hot-reload |
| `tests/unit/test_config_manager.py` | Config TOML read/write/validate |
| `tests/unit/test_data_manager.py` | Parquet listing, preview, fetch jobs |
| `tests/unit/test_backtest_runner.py` | Backtest execution and progress |
| `tests/unit/test_api_pipeline.py` | Pipeline REST + WebSocket endpoints |
| `tests/unit/test_api_config.py` | Config REST endpoints |
| `tests/unit/test_api_analysis.py` | Analysis REST endpoints |
| `tests/unit/test_api_data.py` | Data REST endpoints |

### Frontend (React — `ui/`)

| File | Responsibility |
|------|---------------|
| `ui/package.json` | Dependencies and scripts |
| `ui/tsconfig.json` | TypeScript config |
| `ui/vite.config.ts` | Vite build config (output to `src/mev_kit/ui/static/`) |
| `ui/tailwind.config.ts` | Tailwind with Dense Pro color palette |
| `ui/index.html` | SPA entry point |
| `ui/src/main.tsx` | React mount + router |
| `ui/src/App.tsx` | Route definitions + Layout wrapper |
| `ui/src/api/client.ts` | Fetch wrapper for REST API |
| `ui/src/api/ws.ts` | WebSocket connection with auto-reconnect |
| `ui/src/api/types.ts` | TypeScript types matching Pydantic models |
| `ui/src/hooks/usePipeline.ts` | Hook: pipeline status + metrics via WebSocket |
| `ui/src/hooks/useWebSocket.ts` | Hook: generic WebSocket with reconnect |
| `ui/src/components/Layout.tsx` | Icon sidebar + page shell |
| `ui/src/components/panels/MetricsStrip.tsx` | Top metrics bar |
| `ui/src/components/panels/PnlChart.tsx` | Cumulative P&L line chart |
| `ui/src/components/panels/SpreadHistogram.tsx` | Spread distribution histogram |
| `ui/src/components/panels/OpportunityFeed.tsx` | Live scrolling opportunity table |
| `ui/src/components/panels/LivePrices.tsx` | DEX/CEX price display |
| `ui/src/components/panels/HotParams.tsx` | Inline-editable params with Apply |
| `ui/src/components/panels/LogStream.tsx` | Scrolling log output |
| `ui/src/components/panels/PipelineControls.tsx` | Start/Stop/Mode selector |
| `ui/src/components/common/DataTable.tsx` | Sortable, filterable, paginated table |
| `ui/src/components/common/Modal.tsx` | Reusable modal dialog |
| `ui/src/components/common/Toast.tsx` | Toast notification system |
| `ui/src/pages/Dashboard.tsx` | Configurable panel grid (react-grid-layout) |
| `ui/src/pages/Backtest.tsx` | Config form → run → results view |
| `ui/src/pages/Config.tsx` | Full config editor with profiles |
| `ui/src/pages/Analysis.tsx` | Results explorer with charts + trade table |
| `ui/src/pages/Data.tsx` | File browser + fetch forms |
| `ui/src/pages/Learn.tsx` | Guide renderer + external links |

---

## Phase 1: Backend Foundation

### Task 1: Add dependencies and create package structure

**Files:**
- Modify: `pyproject.toml`
- Create: `src/mev_kit/ui/__init__.py`
- Create: `src/mev_kit/ui/routers/__init__.py`

- [ ] **Step 1: Add FastAPI and uvicorn to pyproject.toml**

Add to the `dependencies` list in `pyproject.toml`:

```toml
"fastapi>=0.111",
"uvicorn[standard]>=0.29",
"python-multipart>=0.0.9",
"markdown>=3.6",
"pygments>=2.17",
```

- [ ] **Step 2: Create the ui package**

Create `src/mev_kit/ui/__init__.py`:

```python
"""mev-kit Web UI — FastAPI server + React dashboard."""
```

Create `src/mev_kit/ui/routers/__init__.py`:

```python
"""API route modules."""
```

- [ ] **Step 3: Install updated dependencies**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Successful install with fastapi, uvicorn added

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/mev_kit/ui/
git commit -m "feat(ui): add FastAPI deps and ui package structure"
```

---

### Task 2: PipelineManager

**Files:**
- Create: `src/mev_kit/ui/pipeline_manager.py`
- Test: `tests/unit/test_pipeline_manager.py`

- [ ] **Step 1: Write failing tests for PipelineManager**

Create `tests/unit/test_pipeline_manager.py`:

```python
"""Tests for PipelineManager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mev_kit.ui.pipeline_manager import PipelineManager


class TestPipelineManager:

    def setup_method(self) -> None:
        PipelineManager._instance = None

    def test_singleton(self) -> None:
        mgr1 = PipelineManager.get()
        mgr2 = PipelineManager.get()
        assert mgr1 is mgr2

    def test_initial_state_is_idle(self) -> None:
        mgr = PipelineManager.get()
        status = mgr.status()
        assert status["state"] == "idle"
        assert status["mode"] is None

    @pytest.mark.asyncio
    async def test_start_transitions_to_running(self) -> None:
        mgr = PipelineManager.get()

        with patch("mev_kit.ui.pipeline_manager._build_pipeline") as mock_build:
            mock_pipeline = AsyncMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline.updates_processed = 0
            mock_pipeline.opportunities_detected = 0
            mock_pipeline.opportunities_executed = 0
            mock_pipeline.total_profit_sol = 0.0
            mock_pipeline.consecutive_misses = 0
            mock_pipeline._update_queue = AsyncMock()
            mock_pipeline._update_queue.qsize.return_value = 0
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {"min_spread_bps": 15.0})
            status = mgr.status()
            assert status["state"] == "running"
            assert status["mode"] == "paper"

            await mgr.stop()

    @pytest.mark.asyncio
    async def test_stop_transitions_to_idle(self) -> None:
        mgr = PipelineManager.get()

        with patch("mev_kit.ui.pipeline_manager._build_pipeline") as mock_build:
            mock_pipeline = AsyncMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.updates_processed = 0
            mock_pipeline.opportunities_detected = 0
            mock_pipeline.opportunities_executed = 0
            mock_pipeline.total_profit_sol = 0.0
            mock_pipeline.consecutive_misses = 0
            mock_pipeline._update_queue = AsyncMock()
            mock_pipeline._update_queue.qsize.return_value = 0
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {})
            await mgr.stop()
            assert mgr.status()["state"] == "idle"

    @pytest.mark.asyncio
    async def test_hot_reload_updates_detector(self) -> None:
        mgr = PipelineManager.get()

        with patch("mev_kit.ui.pipeline_manager._build_pipeline") as mock_build:
            mock_detector = MagicMock()
            mock_detector.min_spread_bps = 15.0
            mock_detector.position_size_sol = 0.01

            mock_pipeline = AsyncMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline.detector = mock_detector
            mock_pipeline.updates_processed = 0
            mock_pipeline.opportunities_detected = 0
            mock_pipeline.opportunities_executed = 0
            mock_pipeline.total_profit_sol = 0.0
            mock_pipeline.consecutive_misses = 0
            mock_pipeline._update_queue = AsyncMock()
            mock_pipeline._update_queue.qsize.return_value = 0
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {})
            mgr.hot_reload({"min_spread_bps": 25.0})
            assert mock_detector.min_spread_bps == 25.0

            await mgr.stop()

    @pytest.mark.asyncio
    async def test_status_includes_metrics(self) -> None:
        mgr = PipelineManager.get()

        with patch("mev_kit.ui.pipeline_manager._build_pipeline") as mock_build:
            mock_pipeline = AsyncMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline.updates_processed = 100
            mock_pipeline.opportunities_detected = 10
            mock_pipeline.opportunities_executed = 8
            mock_pipeline.total_profit_sol = 1.5
            mock_pipeline.consecutive_misses = 1
            mock_pipeline._update_queue = AsyncMock()
            mock_pipeline._update_queue.qsize.return_value = 5
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {})
            status = mgr.status()

            assert status["metrics"]["updates_processed"] == 100
            assert status["metrics"]["opportunities_detected"] == 10
            assert status["metrics"]["total_profit_sol"] == 1.5
            assert status["metrics"]["queue_size"] == 5

            await mgr.stop()

    @pytest.mark.asyncio
    async def test_cannot_start_while_running(self) -> None:
        mgr = PipelineManager.get()

        with patch("mev_kit.ui.pipeline_manager._build_pipeline") as mock_build:
            mock_pipeline = AsyncMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline.updates_processed = 0
            mock_pipeline.opportunities_detected = 0
            mock_pipeline.opportunities_executed = 0
            mock_pipeline.total_profit_sol = 0.0
            mock_pipeline.consecutive_misses = 0
            mock_pipeline._update_queue = AsyncMock()
            mock_pipeline._update_queue.qsize.return_value = 0
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {})

            with pytest.raises(RuntimeError, match="already running"):
                await mgr.start("paper", {})

            await mgr.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_pipeline_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mev_kit.ui.pipeline_manager'`

- [ ] **Step 3: Implement PipelineManager**

Create `src/mev_kit/ui/pipeline_manager.py`:

```python
"""PipelineManager — singleton that owns the running Pipeline instance.

Provides start/stop/status/hot-reload for the web UI. Pushes metrics
over async generators for WebSocket consumers.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import structlog

from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator, Simulator
from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
from mev_kit.adapters.sinks.jito_bundle import JitoBundleSink
from mev_kit.adapters.sinks.paper_trade import BacktestSink, PaperTradeSink
from mev_kit.models import PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()

# Hot-reloadable params that can be patched on a live detector
HOT_PARAMS = {"min_spread_bps", "fee_bps", "position_size_sol", "max_position_size_sol"}


class PipelineManager:
    """Singleton managing the running Pipeline instance."""

    _instance: PipelineManager | None = None

    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._task: asyncio.Task | None = None
        self._mode: str | None = None
        self._start_time: float | None = None
        self._recent_opportunities: list[dict] = []
        self._max_recent = 200

    @classmethod
    def get(cls) -> PipelineManager:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        """Return current pipeline state and metrics."""
        if self._pipeline is None or self._task is None:
            return {"state": "idle", "mode": None, "metrics": {}}

        if self._task.done():
            return {"state": "idle", "mode": None, "metrics": {}}

        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        p = self._pipeline
        updates = p.updates_processed
        detected = p.opportunities_detected

        return {
            "state": "running",
            "mode": self._mode,
            "metrics": {
                "updates_processed": updates,
                "opportunities_detected": detected,
                "opportunities_simulated": p.opportunities_simulated,
                "opportunities_profitable": p.opportunities_profitable,
                "opportunities_executed": p.opportunities_executed,
                "total_profit_sol": round(p.total_profit_sol, 6),
                "consecutive_misses": p.consecutive_misses,
                "detection_rate": round(detected / max(1, updates), 4),
                "elapsed_seconds": round(elapsed, 1),
                "queue_size": p._update_queue.qsize(),
            },
        }

    async def start(self, mode: str, config_overrides: dict) -> None:
        """Start the pipeline in the given mode."""
        if self._pipeline is not None and self._task is not None and not self._task.done():
            raise RuntimeError("Pipeline already running")

        pipeline = _build_pipeline(mode, config_overrides)
        self._pipeline = pipeline
        self._mode = mode
        self._start_time = time.monotonic()
        self._recent_opportunities = []
        self._task = asyncio.create_task(pipeline.run())
        logger.info("pipeline_manager.started", mode=mode)

    async def stop(self) -> None:
        """Stop the running pipeline."""
        if self._pipeline is None:
            return
        await self._pipeline.stop()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._pipeline = None
        self._task = None
        self._mode = None
        self._start_time = None
        logger.info("pipeline_manager.stopped")

    def hot_reload(self, params: dict) -> None:
        """Patch hot-reloadable params on the live detector."""
        if self._pipeline is None:
            raise RuntimeError("No pipeline running")
        detector = self._pipeline.detector
        for key, value in params.items():
            if key in HOT_PARAMS and hasattr(detector, key):
                setattr(detector, key, value)
                logger.info("pipeline_manager.hot_reload", param=key, value=value)

    def add_opportunity(self, opp: dict) -> None:
        """Track a recent opportunity for the feed."""
        self._recent_opportunities.insert(0, opp)
        if len(self._recent_opportunities) > self._max_recent:
            self._recent_opportunities.pop()

    @property
    def recent_opportunities(self) -> list[dict]:
        return list(self._recent_opportunities)


def _build_pipeline(mode: str, config_overrides: dict) -> Pipeline:
    """Build a Pipeline from mode and config overrides."""
    config = PipelineConfig(mode=mode, **{
        k: v for k, v in config_overrides.items()
        if k in PipelineConfig.model_fields
    })

    # Build adapters based on mode
    adapters = []
    helius_key = os.environ.get("HELIUS_API_KEY", config.helius_api_key)

    if mode in ("paper", "live"):
        if helius_key:
            adapters.append(HeliusWSAdapter({"helius_api_key": helius_key}))
        adapters.append(BinanceWSAdapter({"symbol": "solusdt"}))
    # Backtest mode uses ParquetReplayAdapter — handled by BacktestRunner

    detector = CEXDEXArbDetector({
        "min_spread_bps": config.min_spread_bps,
        "fee_bps": config_overrides.get("fee_bps", 30.0),
        "pair": "SOL/USDC",
        "position_size_sol": config.position_size_sol,
    })

    # Simulator
    if config.simulate_before_execute and mode != "backtest":
        rpc_url = os.environ.get("HELIUS_RPC_URL", config.helius_rpc_url)
        simulator: Simulator = RPCSimulator({"rpc_url": rpc_url})
    else:
        simulator = PassthroughSimulator({})

    # Sink
    if mode == "live":
        sink = JitoBundleSink({
            "jito_url": config.jito_block_engine_url,
            "tip_percentage": config.tip_percentage,
            "keypair_path": os.environ.get("WALLET_KEYPAIR_PATH", ""),
            "dry_run": config_overrides.get("dry_run", False),
        })
    else:
        sink = PaperTradeSink({"db_path": config.results_db})

    return Pipeline(
        config=config,
        adapters=adapters,
        detector=detector,
        simulator=simulator,
        sink=sink,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && pytest tests/unit/test_pipeline_manager.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mev_kit/ui/pipeline_manager.py tests/unit/test_pipeline_manager.py
git commit -m "feat(ui): add PipelineManager with start/stop/status/hot-reload"
```

---

### Task 3: ConfigManager

**Files:**
- Create: `src/mev_kit/ui/config_manager.py`
- Test: `tests/unit/test_config_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_config_manager.py`:

```python
"""Tests for ConfigManager."""

from __future__ import annotations

import os
import tempfile

import pytest

from mev_kit.ui.config_manager import ConfigManager


class TestConfigManager:

    def test_list_profiles(self) -> None:
        mgr = ConfigManager("config/")
        profiles = mgr.list_profiles()
        assert "free" in profiles
        assert "pro" in profiles

    def test_load_profile(self) -> None:
        mgr = ConfigManager("config/")
        config = mgr.load("free")
        assert config["strategy"]["min_spread_bps"] == 15.0
        assert config["pipeline"]["mode"] == "paper"

    def test_load_nonexistent_raises(self) -> None:
        mgr = ConfigManager("config/")
        with pytest.raises(FileNotFoundError):
            mgr.load("nonexistent")

    def test_save_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ConfigManager(tmpdir)
            data = {
                "pipeline": {"mode": "paper", "strategy": "cex_dex_arb"},
                "strategy": {"min_spread_bps": 20.0},
            }
            mgr.save("test_profile", data)
            assert os.path.exists(os.path.join(tmpdir, "test_profile.toml"))

            loaded = mgr.load("test_profile")
            assert loaded["strategy"]["min_spread_bps"] == 20.0

    def test_save_and_reload_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ConfigManager(tmpdir)
            data = {
                "pipeline": {"mode": "live", "strategy": "cex_dex_arb"},
                "strategy": {"min_spread_bps": 8.0, "position_size_sol": 5.0},
                "risk": {"max_daily_loss_sol": 50.0, "circuit_breaker_enabled": True},
            }
            mgr.save("roundtrip", data)
            loaded = mgr.load("roundtrip")
            assert loaded["strategy"]["min_spread_bps"] == 8.0
            assert loaded["risk"]["circuit_breaker_enabled"] is True

    def test_env_key_status(self) -> None:
        mgr = ConfigManager("config/")
        status = mgr.env_key_status()
        # Keys should be present (true/false), never the actual value
        assert "HELIUS_API_KEY" in status
        assert isinstance(status["HELIUS_API_KEY"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_config_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ConfigManager**

Create `src/mev_kit/ui/config_manager.py`:

```python
"""ConfigManager — TOML config read/write/validate with profile management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomli


class ConfigManager:
    """Manages TOML config files for mev-kit profiles."""

    def __init__(self, config_dir: str) -> None:
        self.config_dir = Path(config_dir)

    def list_profiles(self) -> list[str]:
        """List available config profile names (without .toml extension)."""
        if not self.config_dir.exists():
            return []
        return sorted(
            p.stem for p in self.config_dir.glob("*.toml")
        )

    def load(self, profile: str) -> dict[str, Any]:
        """Load a TOML config file by profile name."""
        path = self.config_dir / f"{profile}.toml"
        if not path.exists():
            raise FileNotFoundError(f"Config profile not found: {path}")
        with open(path, "rb") as f:
            return tomli.load(f)

    def save(self, profile: str, data: dict[str, Any]) -> None:
        """Save config data to a TOML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / f"{profile}.toml"
        with open(path, "w") as f:
            _write_toml(f, data)

    def env_key_status(self) -> dict[str, bool]:
        """Return which API keys are set in the environment (never values)."""
        keys = [
            "HELIUS_API_KEY",
            "HELIUS_RPC_URL",
            "SOLANA_RPC_URL",
            "JITO_BLOCK_ENGINE_URL",
            "WALLET_KEYPAIR_PATH",
        ]
        return {k: bool(os.environ.get(k)) for k in keys}


def _write_toml(f: Any, data: dict[str, Any], prefix: str = "") -> None:
    """Write a nested dict as TOML format."""
    # Write top-level scalars first
    for key, value in data.items():
        if not isinstance(value, dict):
            f.write(f"{key} = {_toml_value(value)}\n")

    # Then sections
    for key, value in data.items():
        if isinstance(value, dict):
            section = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            f.write(f"\n[{section}]\n")
            for k, v in value.items():
                f.write(f"{k} = {_toml_value(v)}\n")


def _toml_value(v: Any) -> str:
    """Convert a Python value to TOML string representation."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        items = ", ".join(f'"{i}"' if isinstance(i, str) else str(i) for i in v)
        return f"[{items}]"
    return str(v)
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_config_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mev_kit/ui/config_manager.py tests/unit/test_config_manager.py
git commit -m "feat(ui): add ConfigManager for TOML profile management"
```

---

### Task 4: DataManager

**Files:**
- Create: `src/mev_kit/ui/data_manager.py`
- Test: `tests/unit/test_data_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_data_manager.py`:

```python
"""Tests for DataManager."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest

from mev_kit.ui.data_manager import DataManager


def _create_test_parquet(path: str) -> None:
    df = pl.DataFrame({
        "pool_address": ["addr1", "addr2"],
        "price": [148.0, 149.0],
        "timestamp": [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)],
    })
    df.write_parquet(path)


class TestDataManager:

    def test_list_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_test_parquet(os.path.join(tmpdir, "test.parquet"))
            mgr = DataManager(tmpdir)
            files = mgr.list_files()
            assert len(files) == 1
            assert files[0]["name"] == "test.parquet"
            assert files[0]["rows"] == 2

    def test_list_files_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = DataManager(tmpdir)
            assert mgr.list_files() == []

    def test_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_test_parquet(os.path.join(tmpdir, "test.parquet"))
            mgr = DataManager(tmpdir)
            preview = mgr.preview("test.parquet", limit=1)
            assert len(preview["rows"]) == 1
            assert "pool_address" in preview["columns"]

    def test_preview_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = DataManager(tmpdir)
            with pytest.raises(FileNotFoundError):
                mgr.preview("nope.parquet")

    def test_delete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.parquet")
            _create_test_parquet(path)
            mgr = DataManager(tmpdir)
            mgr.delete("test.parquet")
            assert not os.path.exists(path)

    def test_delete_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = DataManager(tmpdir)
            with pytest.raises(FileNotFoundError):
                mgr.delete("nope.parquet")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_data_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DataManager**

Create `src/mev_kit/ui/data_manager.py`:

```python
"""DataManager — Parquet file CRUD and background fetch jobs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger()


class DataManager:
    """Manages Parquet data files and fetch jobs."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self._active_jobs: dict[str, dict] = {}

    def list_files(self) -> list[dict[str, Any]]:
        """List Parquet files with metadata."""
        if not self.data_dir.exists():
            return []
        files = []
        for p in sorted(self.data_dir.glob("*.parquet")):
            try:
                df = pl.scan_parquet(p)
                rows = df.select(pl.len()).collect().item()
                cols = df.columns
                files.append({
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "rows": rows,
                    "columns": cols,
                    "modified": p.stat().st_mtime,
                })
            except Exception:
                files.append({
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "rows": 0,
                    "columns": [],
                    "modified": p.stat().st_mtime,
                })
        return files

    def preview(self, filename: str, limit: int = 10) -> dict[str, Any]:
        """Preview first N rows of a Parquet file."""
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        df = pl.read_parquet(path).head(limit)
        return {
            "columns": df.columns,
            "rows": df.to_dicts(),
            "total_rows": pl.scan_parquet(path).select(pl.len()).collect().item(),
        }

    def delete(self, filename: str) -> None:
        """Delete a Parquet file."""
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        path.unlink()
        logger.info("data_manager.deleted", file=filename)
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_data_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mev_kit/ui/data_manager.py tests/unit/test_data_manager.py
git commit -m "feat(ui): add DataManager for Parquet file operations"
```

---

### Task 5: BacktestRunner

**Files:**
- Create: `src/mev_kit/ui/backtest_runner.py`
- Test: `tests/unit/test_backtest_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_backtest_runner.py`:

```python
"""Tests for BacktestRunner."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest

from mev_kit.ui.backtest_runner import BacktestRunner


def _create_test_data(tmpdir: str) -> str:
    path = os.path.join(tmpdir, "test.parquet")
    rows = []
    for i in range(10):
        rows.append({
            "pool_address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "dex": "raydium",
            "base_mint": "SOL",
            "quote_mint": "USDC",
            "base_reserve": 1000.0,
            "quote_reserve": 148000.0 + i * 100,
            "price": 148.0 + i * 0.1,
            "fee_bps": 30,
            "slot": 280000000 + i,
            "timestamp": datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
        })
    pl.DataFrame(rows).write_parquet(path)
    return path


class TestBacktestRunner:

    def test_initial_state(self) -> None:
        runner = BacktestRunner()
        assert runner.status()["state"] == "idle"

    @pytest.mark.asyncio
    async def test_run_backtest_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_test_data(tmpdir)
            runner = BacktestRunner()
            await runner.run(
                data_path=data_path,
                config={"min_spread_bps": 15.0, "position_size_sol": 1.0},
            )
            status = runner.status()
            assert status["state"] == "completed"
            assert status["results"]["total_trades"] >= 0

    @pytest.mark.asyncio
    async def test_status_has_results_after_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_test_data(tmpdir)
            runner = BacktestRunner()
            await runner.run(data_path=data_path, config={})
            results = runner.status()["results"]
            assert "total_trades" in results
            assert "total_profit_sol" in results
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_backtest_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement BacktestRunner**

Create `src/mev_kit/ui/backtest_runner.py`:

```python
"""BacktestRunner — async backtest execution with progress tracking."""

from __future__ import annotations

from typing import Any

import structlog

from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.base import PassthroughSimulator
from mev_kit.adapters.sinks.paper_trade import BacktestSink
from mev_kit.models import ExecutionMode, PipelineConfig
from mev_kit.pipeline.runner import Pipeline
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

logger = structlog.get_logger()


class BacktestRunner:
    """Runs backtests and tracks progress."""

    def __init__(self) -> None:
        self._state: str = "idle"
        self._pipeline: Pipeline | None = None
        self._sink: BacktestSink | None = None
        self._results: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        """Return current backtest state and results."""
        result: dict[str, Any] = {"state": self._state}
        if self._pipeline and self._state == "running":
            result["progress"] = {
                "updates_processed": self._pipeline.updates_processed,
                "opportunities_detected": self._pipeline.opportunities_detected,
            }
        if self._state == "completed":
            result["results"] = self._results
        return result

    async def run(self, data_path: str, config: dict) -> None:
        """Run a backtest against Parquet data."""
        self._state = "running"

        pipeline_config = PipelineConfig(
            mode=ExecutionMode.BACKTEST,
            simulate_before_execute=config.get("simulate_before_execute", False),
            min_spread_bps=config.get("min_spread_bps", 15.0),
            position_size_sol=config.get("position_size_sol", 0.01),
            circuit_breaker_enabled=False,
        )

        adapter = ParquetReplayAdapter({"path": data_path, "source_type": "pool"})
        detector = CEXDEXArbDetector({
            "min_spread_bps": pipeline_config.min_spread_bps,
            "fee_bps": config.get("fee_bps", 30.0),
            "pair": "SOL/USDC",
            "position_size_sol": pipeline_config.position_size_sol,
        })
        simulator = PassthroughSimulator({})
        self._sink = BacktestSink({"output_path": None})

        self._pipeline = Pipeline(
            config=pipeline_config,
            adapters=[adapter],
            detector=detector,
            simulator=simulator,
            sink=self._sink,
        )

        try:
            await self._pipeline.run()
        finally:
            self._state = "completed"
            self._results = self._compute_results()

    def _compute_results(self) -> dict[str, Any]:
        """Compute summary from backtest sink results."""
        if not self._sink or not self._sink.results:
            return {"total_trades": 0, "total_profit_sol": 0.0}

        results = self._sink.results
        profits = [r["simulated_profit_sol"] for r in results]
        return {
            "total_trades": len(results),
            "total_profit_sol": round(sum(profits), 6),
            "avg_profit_sol": round(sum(profits) / len(profits), 6) if profits else 0.0,
            "win_rate": round(sum(1 for p in profits if p > 0) / len(profits), 4) if profits else 0.0,
            "best_trade_sol": round(max(profits), 6) if profits else 0.0,
            "worst_trade_sol": round(min(profits), 6) if profits else 0.0,
            "avg_spread_bps": round(
                sum(r["spread_bps"] for r in results) / len(results), 1
            ) if results else 0.0,
            "trades": results,
        }
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_backtest_runner.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/mev_kit/ui/backtest_runner.py tests/unit/test_backtest_runner.py
git commit -m "feat(ui): add BacktestRunner with progress tracking"
```

---

### Task 6: FastAPI Server + Pipeline Router

**Files:**
- Create: `src/mev_kit/ui/server.py`
- Create: `src/mev_kit/ui/routers/pipeline.py`
- Test: `tests/unit/test_api_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_api_pipeline.py`:

```python
"""Tests for Pipeline API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mev_kit.ui.server import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app(config_dir="config/", data_dir="./data/")
    return TestClient(app)


class TestPipelineAPI:

    def test_get_status_idle(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.status.return_value = {"state": "idle", "mode": None, "metrics": {}}
            mock_cls.get.return_value = mock_mgr

            resp = client.get("/api/pipeline/status")
            assert resp.status_code == 200
            assert resp.json()["state"] == "idle"

    def test_post_start(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.start = MagicMock()  # sync mock for the endpoint
            mock_cls.get.return_value = mock_mgr

            resp = client.post("/api/pipeline/start", json={
                "mode": "paper",
                "config": {"min_spread_bps": 20.0},
            })
            assert resp.status_code == 200

    def test_post_stop(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.stop = MagicMock()
            mock_cls.get.return_value = mock_mgr

            resp = client.post("/api/pipeline/stop")
            assert resp.status_code == 200

    def test_patch_params(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_cls.get.return_value = mock_mgr

            resp = client.patch("/api/pipeline/params", json={
                "min_spread_bps": 25.0,
            })
            assert resp.status_code == 200
            mock_mgr.hot_reload.assert_called_once_with({"min_spread_bps": 25.0})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/unit/test_api_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the FastAPI server and pipeline router**

Create `src/mev_kit/ui/server.py`:

```python
"""FastAPI server — serves the API and the React SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mev_kit.ui.routers import pipeline, config, backtest, analysis, data, docs


def create_app(config_dir: str = "config/", data_dir: str = "./data/") -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="mev-kit", version="0.1.0")

    # Store shared state
    app.state.config_dir = config_dir
    app.state.data_dir = data_dir

    # Mount API routers
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
    app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
    app.include_router(data.router, prefix="/api/data", tags=["data"])
    app.include_router(docs.router, prefix="/api/docs", tags=["docs"])

    # Serve static React app (if built)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
```

Create `src/mev_kit/ui/routers/pipeline.py`:

```python
"""Pipeline control and monitoring endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import structlog

from mev_kit.ui.pipeline_manager import PipelineManager

logger = structlog.get_logger()
router = APIRouter()


@router.get("/status")
async def get_status() -> dict[str, Any]:
    """Get current pipeline state and metrics."""
    return PipelineManager.get().status()


@router.post("/start")
async def start_pipeline(body: dict[str, Any]) -> dict[str, str]:
    """Start the pipeline in the specified mode."""
    mode = body.get("mode", "paper")
    config = body.get("config", {})
    try:
        await PipelineManager.get().start(mode, config)
        return {"status": "started", "mode": mode}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


@router.post("/stop")
async def stop_pipeline() -> dict[str, str]:
    """Stop the running pipeline."""
    await PipelineManager.get().stop()
    return {"status": "stopped"}


@router.patch("/params")
async def patch_params(body: dict[str, Any]) -> dict[str, str]:
    """Hot-reload strategy parameters on the running pipeline."""
    try:
        PipelineManager.get().hot_reload(body)
        return {"status": "updated", "params": list(body.keys())}
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}


@router.websocket("/ws")
async def pipeline_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint streaming pipeline metrics at ~1Hz."""
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
```

- [ ] **Step 4: Create stub routers so imports don't fail**

Create minimal stub files for the remaining routers:

`src/mev_kit/ui/routers/config.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```

`src/mev_kit/ui/routers/backtest.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```

`src/mev_kit/ui/routers/analysis.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```

`src/mev_kit/ui/routers/data.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```

`src/mev_kit/ui/routers/docs.py`:
```python
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 5: Run tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_api_pipeline.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/mev_kit/ui/server.py src/mev_kit/ui/routers/
git add tests/unit/test_api_pipeline.py
git commit -m "feat(ui): add FastAPI server with pipeline REST + WebSocket endpoints"
```

---

### Task 7: Config, Analysis, Data, Docs Routers

**Files:**
- Modify: `src/mev_kit/ui/routers/config.py`
- Modify: `src/mev_kit/ui/routers/backtest.py`
- Modify: `src/mev_kit/ui/routers/analysis.py`
- Modify: `src/mev_kit/ui/routers/data.py`
- Modify: `src/mev_kit/ui/routers/docs.py`
- Test: `tests/unit/test_api_config.py`
- Test: `tests/unit/test_api_analysis.py`
- Test: `tests/unit/test_api_data.py`

- [ ] **Step 1: Write tests for config API**

Create `tests/unit/test_api_config.py`:

```python
"""Tests for Config API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mev_kit.ui.server import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app(config_dir="config/", data_dir="./data/")
    return TestClient(app)


class TestConfigAPI:

    def test_list_profiles(self, client: TestClient) -> None:
        resp = client.get("/api/config/profiles")
        assert resp.status_code == 200
        profiles = resp.json()
        assert "free" in profiles
        assert "pro" in profiles

    def test_load_profile(self, client: TestClient) -> None:
        resp = client.get("/api/config?profile=free")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
        assert "pipeline" in data

    def test_env_status(self, client: TestClient) -> None:
        resp = client.get("/api/config/env")
        assert resp.status_code == 200
        data = resp.json()
        assert "HELIUS_API_KEY" in data
```

- [ ] **Step 2: Implement config router**

Replace `src/mev_kit/ui/routers/config.py`:

```python
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
```

- [ ] **Step 3: Implement backtest router**

Replace `src/mev_kit/ui/routers/backtest.py`:

```python
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
```

- [ ] **Step 4: Implement analysis router**

Replace `src/mev_kit/ui/routers/analysis.py`:

```python
"""Results analysis endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/{db_name}")
async def get_summary(request: Request, db_name: str) -> dict[str, Any]:
    db_path = Path(request.app.state.data_dir) / db_name
    if not db_path.exists():
        return {"error": f"Database not found: {db_name}"}

    async with aiosqlite.connect(str(db_path)) as db:
        async with db.execute("SELECT COUNT(*) FROM paper_trades") as cur:
            total = (await cur.fetchone())[0]

        if total == 0:
            return {"total_trades": 0}

        async with db.execute("""
            SELECT
                SUM(simulated_profit_sol), AVG(simulated_profit_sol),
                MAX(simulated_profit_sol), MIN(simulated_profit_sol),
                AVG(spread_bps), MIN(timestamp), MAX(timestamp),
                SUM(CASE WHEN simulated_profit_sol > 0 THEN 1 ELSE 0 END)
            FROM paper_trades
        """) as cur:
            row = await cur.fetchone()

    return {
        "total_trades": total,
        "total_profit_sol": round(row[0] or 0, 6),
        "avg_profit_sol": round(row[1] or 0, 6),
        "best_trade_sol": round(row[2] or 0, 6),
        "worst_trade_sol": round(row[3] or 0, 6),
        "avg_spread_bps": round(row[4] or 0, 1),
        "first_trade": row[5],
        "last_trade": row[6],
        "win_rate": round((row[7] or 0) / max(1, total), 4),
    }


@router.get("/{db_name}/trades")
async def get_trades(
    request: Request,
    db_name: str,
    page: int = 1,
    per_page: int = 50,
    sort: str = "timestamp",
    direction: str | None = None,
) -> dict[str, Any]:
    db_path = Path(request.app.state.data_dir) / db_name
    if not db_path.exists():
        return {"error": f"Database not found: {db_name}"}

    offset = (page - 1) * per_page
    where = ""
    params: list = []
    if direction:
        where = "WHERE direction = ?"
        params.append(direction)

    allowed_sorts = {"timestamp", "spread_bps", "simulated_profit_sol", "dex_price"}
    sort_col = sort if sort in allowed_sorts else "timestamp"

    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(f"SELECT COUNT(*) FROM paper_trades {where}", params) as cur:
            total = (await cur.fetchone())[0]

        query = f"SELECT * FROM paper_trades {where} ORDER BY {sort_col} DESC LIMIT ? OFFSET ?"
        async with db.execute(query, [*params, per_page, offset]) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return {
        "trades": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }
```

- [ ] **Step 5: Implement data router**

Replace `src/mev_kit/ui/routers/data.py`:

```python
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
```

- [ ] **Step 6: Implement docs router**

Replace `src/mev_kit/ui/routers/docs.py`:

```python
"""Documentation and guides endpoints."""

from __future__ import annotations

from pathlib import Path

import markdown
from fastapi import APIRouter

router = APIRouter()

GUIDES_DIR = Path(__file__).parent.parent / "guides"


@router.get("/guides")
async def list_guides() -> list[dict[str, str]]:
    if not GUIDES_DIR.exists():
        return []
    guides = []
    for p in sorted(GUIDES_DIR.glob("*.md")):
        title = p.stem.split("-", 1)[-1].replace("-", " ").title()
        # Read first line for actual title
        first_line = p.read_text().split("\n")[0].lstrip("# ").strip()
        if first_line:
            title = first_line
        guides.append({"slug": p.stem, "title": title})
    return guides


@router.get("/guides/{slug}")
async def get_guide(slug: str) -> dict[str, str]:
    path = GUIDES_DIR / f"{slug}.md"
    if not path.exists():
        return {"error": f"Guide not found: {slug}"}
    raw = path.read_text()
    html = markdown.markdown(raw, extensions=["fenced_code", "tables", "codehilite"])
    return {"slug": slug, "markdown": raw, "html": html}
```

- [ ] **Step 7: Run all tests**

Run: `source .venv/bin/activate && pytest tests/unit/test_api_config.py tests/unit/test_api_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/mev_kit/ui/routers/ tests/unit/test_api_config.py
git commit -m "feat(ui): add config, backtest, analysis, data, docs API routers"
```

---

### Task 8: CLI `ui` command

**Files:**
- Modify: `src/mev_kit/cli.py`

- [ ] **Step 1: Add the `ui` command to the CLI**

Add after the existing `analyze` command in `src/mev_kit/cli.py`:

```python
@main.command()
@click.option("--config-dir", default="config/", help="Config directory")
@click.option("--data-dir", default="./data/", help="Data directory")
@click.option("--host", default="127.0.0.1", help="Server host")
@click.option("--port", "-p", default=8080, help="Server port")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
def ui(config_dir: str, data_dir: str, host: str, port: int, no_open: bool) -> None:
    """Launch the web UI dashboard."""
    import uvicorn
    from mev_kit.ui.server import create_app

    app = create_app(config_dir=config_dir, data_dir=data_dir)

    if not no_open:
        import webbrowser
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    click.echo(f"Starting mev-kit UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
```

- [ ] **Step 2: Verify CLI shows the new command**

Run: `source .venv/bin/activate && mev-kit --help`
Expected: Output includes `ui` command with description "Launch the web UI dashboard."

- [ ] **Step 3: Commit**

```bash
git add src/mev_kit/cli.py
git commit -m "feat(ui): add 'mev-kit ui' CLI command to launch web dashboard"
```

---

### Task 9: Educational Guides

**Files:**
- Create: `src/mev_kit/ui/guides/01-mev-on-solana.md`
- Create: `src/mev_kit/ui/guides/02-cex-dex-arb.md`
- Create: `src/mev_kit/ui/guides/03-pipeline.md`
- Create: `src/mev_kit/ui/guides/04-custom-detector.md`
- Create: `src/mev_kit/ui/guides/05-backtesting.md`

- [ ] **Step 1: Write all 5 guides**

Each guide should be a complete markdown file covering the topics specified in the design spec. These are educational content — write them as clear, practical tutorials with code examples. Use the actual mev-kit API and class names.

Guide 1 (`01-mev-on-solana.md`): MEV concepts, Solana vs Ethereum MEV, Jito's role, why SOL/USDC arb exists.

Guide 2 (`02-cex-dex-arb.md`): The specific strategy — Binance vs Raydium price discrepancy, spread calculation formula, fee accounting, BUY_DEX vs SELL_DEX direction logic.

Guide 3 (`03-pipeline.md`): The 5-layer pipeline (Source → Detector → Simulator → Sink → Monitor), adapter pattern, how mode switching works, config-driven composition.

Guide 4 (`04-custom-detector.md`): Tutorial — subclass `Detector`, implement `async def process()`, emit `Opportunity`. Complete code example with a custom spread tracker.

Guide 5 (`05-backtesting.md`): Step-by-step — fetch data with scripts, configure params, run `mev-kit backtest` or use the UI, analyze results, iterate.

- [ ] **Step 2: Verify guides are listed by the API**

Run: `source .venv/bin/activate && python -c "from mev_kit.ui.routers.docs import GUIDES_DIR; print(list(GUIDES_DIR.glob('*.md')))"`
Expected: Prints list of 5 guide paths

- [ ] **Step 3: Commit**

```bash
git add src/mev_kit/ui/guides/
git commit -m "docs(ui): add 5 educational guides for Solana MEV and mev-kit"
```

---

### Task 10: Run all backend tests

- [ ] **Step 1: Run the full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS (existing 56 + new backend tests)

- [ ] **Step 2: Run ruff lint**

Run: `source .venv/bin/activate && ruff check src/mev_kit/ui/ tests/unit/test_pipeline_manager.py tests/unit/test_config_manager.py tests/unit/test_data_manager.py tests/unit/test_backtest_runner.py tests/unit/test_api_pipeline.py tests/unit/test_api_config.py`
Expected: No errors

- [ ] **Step 3: Fix any lint issues and commit**

```bash
git add -A && git commit -m "chore(ui): fix lint issues in backend code"
```

---

## Phase 2: Frontend Foundation

### Task 11: Scaffold React project with Vite + Tailwind

**Files:**
- Create: `ui/package.json`
- Create: `ui/tsconfig.json`
- Create: `ui/vite.config.ts`
- Create: `ui/tailwind.config.ts`
- Create: `ui/postcss.config.js`
- Create: `ui/index.html`
- Create: `ui/src/main.tsx`
- Create: `ui/src/App.tsx`
- Create: `ui/src/index.css`

- [ ] **Step 1: Initialize the project**

Run from project root:
```bash
cd ui && npm create vite@latest . -- --template react-ts
```

If `ui/` doesn't exist, create it first: `mkdir -p ui`

- [ ] **Step 2: Install dependencies**

```bash
cd ui && npm install react-router-dom react-grid-layout lightweight-charts recharts react-markdown remark-gfm lucide-react
npm install -D tailwindcss @tailwindcss/vite @types/react-grid-layout
```

- [ ] **Step 3: Configure Vite to output to src/mev_kit/ui/static/**

Create `ui/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/mev_kit/ui/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/ws": { target: "ws://localhost:8080", ws: true },
    },
  },
});
```

- [ ] **Step 4: Configure Tailwind with Dense Pro colors**

Add to `ui/src/index.css`:

```css
@import "tailwindcss";

@theme {
  --color-bg-main: #1a1a2e;
  --color-bg-panel: #16213e;
  --color-bg-sidebar: #12122a;
  --color-bg-active: #252547;
  --color-border: #2a2a4a;
  --color-text-primary: #e0e0e0;
  --color-text-secondary: #7f8ea3;
  --color-accent-green: #00e676;
  --color-accent-red: #ef5350;
  --color-accent-amber: #ffab00;
  --color-accent-indigo: #6366f1;
}

body {
  background-color: var(--color-bg-main);
  color: var(--color-text-primary);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
  margin: 0;
}

.font-mono {
  font-family: "SF Mono", Monaco, "Cascadia Code", monospace;
}
```

- [ ] **Step 5: Set up App.tsx with router**

Create `ui/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Backtest from "./pages/Backtest";
import Config from "./pages/Config";
import Analysis from "./pages/Analysis";
import Data from "./pages/Data";
import Learn from "./pages/Learn";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/config" element={<Config />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/data" element={<Data />} />
          <Route path="/learn" element={<Learn />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 6: Create stub pages**

Create a stub for each page file (`ui/src/pages/Dashboard.tsx`, `Backtest.tsx`, `Config.tsx`, `Analysis.tsx`, `Data.tsx`, `Learn.tsx`) with a placeholder:

```tsx
export default function Dashboard() {
  return <div className="p-4"><h1 className="text-xl font-semibold">Dashboard</h1></div>;
}
```

(Repeat for each page with the appropriate name.)

- [ ] **Step 7: Verify dev server starts**

Run: `cd ui && npm run dev`
Expected: Vite dev server starts, accessible at http://localhost:5173, shows the page name text

- [ ] **Step 8: Commit**

```bash
git add ui/
echo "ui/node_modules/" >> .gitignore
echo "src/mev_kit/ui/static/" >> .gitignore
echo ".superpowers/" >> .gitignore
git add .gitignore
git commit -m "feat(ui): scaffold React + Vite + Tailwind frontend"
```

---

### Task 12: Layout component (Icon Sidebar)

**Files:**
- Create: `ui/src/components/Layout.tsx`
- Create: `ui/src/api/types.ts`
- Create: `ui/src/api/client.ts`

- [ ] **Step 1: Create TypeScript types matching the backend**

Create `ui/src/api/types.ts`:

```typescript
export interface PipelineStatus {
  state: "idle" | "running" | "stopping";
  mode: string | null;
  metrics: PipelineMetrics;
}

export interface PipelineMetrics {
  updates_processed: number;
  opportunities_detected: number;
  opportunities_simulated: number;
  opportunities_profitable: number;
  opportunities_executed: number;
  total_profit_sol: number;
  consecutive_misses: number;
  detection_rate: number;
  elapsed_seconds: number;
  queue_size: number;
}

export interface Opportunity {
  id: string;
  type: string;
  direction: "BUY_DEX" | "SELL_DEX";
  spread_bps: number;
  estimated_profit_sol: number;
  simulated_profit_sol: number;
  sim_latency_ms: number;
  success: boolean;
  timestamp: string;
}

export interface ConfigProfile {
  pipeline: Record<string, unknown>;
  strategy: Record<string, unknown>;
  ingest?: Record<string, unknown>;
  simulator?: Record<string, unknown>;
  sink?: Record<string, unknown>;
  risk?: Record<string, unknown>;
  data?: Record<string, unknown>;
}

export interface DataFile {
  name: string;
  size_bytes: number;
  rows: number;
  columns: string[];
  modified: number;
}

export interface Guide {
  slug: string;
  title: string;
}

export interface TradeRow {
  id: string;
  timestamp: string;
  type: string;
  direction: string;
  pair: string;
  dex: string;
  dex_price: number;
  reference_price: number;
  spread_bps: number;
  estimated_profit_sol: number;
  simulated_profit_sol: number;
  pool_address: string;
  detector: string;
}
```

- [ ] **Step 2: Create API client**

Create `ui/src/api/client.ts`:

```typescript
const BASE = "";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const get = <T>(path: string) => api<T>(path);

export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });

export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const del = <T>(path: string) =>
  api<T>(path, { method: "DELETE" });
```

- [ ] **Step 3: Implement the Layout with icon sidebar**

Create `ui/src/components/Layout.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Play,
  Settings,
  BarChart3,
  Database,
  BookOpen,
} from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { PipelineStatus } from "../api/types";

const NAV_ITEMS = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/backtest", icon: Play, label: "Backtest" },
  { to: "/config", icon: Settings, label: "Config" },
  { to: "/analysis", icon: BarChart3, label: "Analysis" },
  { to: "/data", icon: Database, label: "Data" },
  { to: "/learn", icon: BookOpen, label: "Learn" },
];

export default function Layout() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);

  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const s = await get<PipelineStatus>("/api/pipeline/status");
        setStatus(s);
      } catch {
        /* server not ready */
      }
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const stateColor =
    status?.state === "running" ? "bg-accent-green" : "bg-text-secondary";

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <nav className="w-[52px] bg-bg-sidebar flex flex-col items-center py-3 gap-3 border-r border-border shrink-0">
        <div className="w-7 h-7 bg-accent-indigo rounded-md flex items-center justify-center text-xs font-bold text-white mb-2">
          M
        </div>
        {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            title={label}
            className={({ isActive }) =>
              `w-8 h-8 rounded-md flex items-center justify-center transition-colors ${
                isActive
                  ? "bg-bg-active text-text-primary"
                  : "text-text-secondary hover:text-text-primary hover:bg-bg-active/50"
              }`
            }
          >
            <Icon size={18} />
          </NavLink>
        ))}
        <div className="mt-auto mb-2" title={status?.state ?? "idle"}>
          <div className={`w-2.5 h-2.5 rounded-full ${stateColor}`} />
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto bg-bg-main">
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Verify layout renders**

Run: `cd ui && npm run dev`
Navigate to http://localhost:5173 — should show sidebar with 6 icons and a status dot. Clicking icons should switch pages (showing stub text).

- [ ] **Step 5: Commit**

```bash
git add ui/src/
git commit -m "feat(ui): add Layout with icon sidebar, API client, and TypeScript types"
```

---

### Task 13: WebSocket hook + Dashboard panels

**Files:**
- Create: `ui/src/hooks/useWebSocket.ts`
- Create: `ui/src/hooks/usePipeline.ts`
- Create: `ui/src/components/panels/MetricsStrip.tsx`
- Create: `ui/src/components/panels/PnlChart.tsx`
- Create: `ui/src/components/panels/SpreadHistogram.tsx`
- Create: `ui/src/components/panels/OpportunityFeed.tsx`
- Create: `ui/src/components/panels/LivePrices.tsx`
- Create: `ui/src/components/panels/HotParams.tsx`
- Create: `ui/src/components/panels/LogStream.tsx`
- Create: `ui/src/components/panels/PipelineControls.tsx`
- Modify: `ui/src/pages/Dashboard.tsx`

- [ ] **Step 1: Create WebSocket hook with auto-reconnect**

Create `ui/src/hooks/useWebSocket.ts` with exponential backoff reconnection (1s, 2s, 4s, max 30s). Returns the latest parsed JSON message.

- [ ] **Step 2: Create usePipeline hook**

Create `ui/src/hooks/usePipeline.ts` that connects to `/ws/pipeline/ws`, parses metrics messages, and maintains a buffer of recent opportunities.

- [ ] **Step 3: Implement all 8 dashboard panels**

Each panel is a self-contained component that receives data via props from the Dashboard page. Follow the Dense Pro aesthetic: `bg-bg-panel`, minimal padding, monospace for data values, color-coded profit/loss.

- `MetricsStrip` — horizontal row of key metrics (P&L, Win%, Opp/min, Updates, Queue, Latency)
- `PnlChart` — TradingView Lightweight Charts line series showing cumulative P&L
- `SpreadHistogram` — Recharts bar chart of spread distribution
- `OpportunityFeed` — scrolling table with time, direction, spread, est P&L, sim P&L, latency, status
- `LivePrices` — DEX price, CEX price, current spread
- `HotParams` — displays current params, edit button toggles inline inputs, Apply button calls PATCH
- `LogStream` — scrolling log entries from `/ws/logs` WebSocket
- `PipelineControls` — mode selector dropdown, Start/Stop buttons, config profile picker

- [ ] **Step 4: Implement Dashboard page with react-grid-layout**

Update `ui/src/pages/Dashboard.tsx` to use `react-grid-layout` with the default Layout A arrangement. Panels are draggable and resizable. Layout saved to localStorage. Reset button restores defaults.

- [ ] **Step 5: Verify dashboard renders with mock data**

Run the Vite dev server and FastAPI backend simultaneously:
```bash
# Terminal 1
source .venv/bin/activate && mev-kit ui --port 8080 --no-open
# Terminal 2
cd ui && npm run dev
```
Navigate to http://localhost:5173 — Dashboard should show all panels in the Dense Pro style.

- [ ] **Step 6: Commit**

```bash
git add ui/src/
git commit -m "feat(ui): add all dashboard panels with react-grid-layout and WebSocket"
```

---

### Task 14: Backtest, Config, Analysis, Data, Learn pages

**Files:**
- Modify: `ui/src/pages/Backtest.tsx`
- Modify: `ui/src/pages/Config.tsx`
- Modify: `ui/src/pages/Analysis.tsx`
- Modify: `ui/src/pages/Data.tsx`
- Modify: `ui/src/pages/Learn.tsx`
- Create: `ui/src/components/common/DataTable.tsx`
- Create: `ui/src/components/common/Modal.tsx`
- Create: `ui/src/components/common/Toast.tsx`

- [ ] **Step 1: Build common components**

Create `DataTable` (sortable, filterable, paginated table), `Modal` (dialog overlay), `Toast` (notification system). All styled with Dense Pro aesthetic.

- [ ] **Step 2: Implement Backtest page**

Three states: config form (file selector + params), running (progress + live metrics), completed (summary cards + charts + trade table + "Tweak & Re-run" button).

- [ ] **Step 3: Implement Config page**

Profile bar (dropdown + Load/Save/Save As). Accordion sections for Strategy, Adapters, Simulator, Sink, Risk, API Keys. Inline validation. Save writes to TOML via PUT `/api/config`.

- [ ] **Step 4: Implement Analysis page**

Database selector. Summary cards row. 4-panel chart grid (P&L curve, spread histogram, hourly heatmap, direction breakdown). Trade table with sort/filter/pagination/export.

- [ ] **Step 5: Implement Data page**

File browser table with Preview/Download/Delete actions. Fetch Historical form (Helius). Fetch Binance form. Active fetches panel with progress.

- [ ] **Step 6: Implement Learn page**

Two-column layout: guide list sidebar + rendered content. Markdown rendered with react-markdown + syntax-highlighted code blocks. External resources section at bottom with categorized links.

- [ ] **Step 7: Verify all pages work end-to-end**

Start both servers. Navigate through all 6 pages. Verify:
- Dashboard: panels render, WebSocket connects, layout is draggable
- Backtest: can select a file and start a run (if test data exists)
- Config: loads free.toml, shows all fields, can save
- Analysis: loads results.db if it exists, shows charts
- Data: lists Parquet files in ./data/
- Learn: renders guide markdown with code highlighting

- [ ] **Step 8: Commit**

```bash
git add ui/src/
git commit -m "feat(ui): implement Backtest, Config, Analysis, Data, Learn pages"
```

---

## Phase 3: Integration and Polish

### Task 15: Build frontend and bundle

- [ ] **Step 1: Build production frontend**

Run:
```bash
cd ui && npm run build
```
Expected: Output in `src/mev_kit/ui/static/` with `index.html` + `assets/`

- [ ] **Step 2: Verify mev-kit ui serves the built app**

Run:
```bash
source .venv/bin/activate && mev-kit ui --port 8080
```
Expected: Opens browser to http://localhost:8080, shows the full React app served by FastAPI

- [ ] **Step 3: Commit**

```bash
git add src/mev_kit/ui/static/
git commit -m "build(ui): bundle production React frontend"
```

---

### Task 16: End-to-end integration test

- [ ] **Step 1: Write E2E test**

Create `tests/integration/test_ui_e2e.py` that:
1. Starts the FastAPI server in a background task
2. Verifies `/api/pipeline/status` returns idle
3. Starts a backtest via `/api/backtest/start` with test Parquet data
4. Polls `/api/backtest/status` until completed
5. Verifies results have trades
6. Verifies `/api/config/profiles` returns free and pro
7. Verifies `/api/data/files` lists Parquet files
8. Verifies `/api/docs/guides` returns 5 guides

- [ ] **Step 2: Run E2E test**

Run: `source .venv/bin/activate && pytest tests/integration/test_ui_e2e.py -v`
Expected: All assertions pass

- [ ] **Step 3: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_ui_e2e.py
git commit -m "test(ui): add end-to-end integration test for web UI API"
```

---

### Task 17: Final polish and lint

- [ ] **Step 1: Run ruff on all backend code**

Run: `source .venv/bin/activate && ruff check src/mev_kit/ui/ tests/`
Fix any issues.

- [ ] **Step 2: Run TypeScript type check**

Run: `cd ui && npx tsc --noEmit`
Fix any type errors.

- [ ] **Step 3: Verify clean install**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Clean install

- [ ] **Step 4: Verify mev-kit ui --help**

Run: `source .venv/bin/activate && mev-kit ui --help`
Expected: Shows usage with --port, --host, --no-open options

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore(ui): final polish — lint clean, types clean, ready to ship"
```
