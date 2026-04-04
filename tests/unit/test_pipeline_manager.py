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
            mock_pipeline._update_queue = MagicMock()
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
            mock_pipeline._update_queue = MagicMock()
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
            mock_pipeline._update_queue = MagicMock()
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
            mock_pipeline._update_queue = MagicMock()
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
            mock_pipeline._update_queue = MagicMock()
            mock_pipeline._update_queue.qsize.return_value = 0
            mock_build.return_value = mock_pipeline

            await mgr.start("paper", {})

            with pytest.raises(RuntimeError, match="already running"):
                await mgr.start("paper", {})

            await mgr.stop()
