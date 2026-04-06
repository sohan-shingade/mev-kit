"""Tests for Pipeline API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
            mock_mgr.start = AsyncMock()
            mock_cls.get.return_value = mock_mgr
            resp = client.post(
                "/api/pipeline/start",
                json={"mode": "paper", "config": {"min_spread_bps": 20.0}},
            )
            assert resp.status_code == 200

    def test_post_stop(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.stop = AsyncMock()
            mock_cls.get.return_value = mock_mgr
            resp = client.post("/api/pipeline/stop")
            assert resp.status_code == 200

    def test_patch_params(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_cls.get.return_value = mock_mgr
            resp = client.patch("/api/pipeline/params", json={"min_spread_bps": 25.0})
            assert resp.status_code == 200
            mock_mgr.hot_reload.assert_called_once_with({"min_spread_bps": 25.0})

    def test_start_from_backtest(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.start = AsyncMock()
            mock_cls.get.return_value = mock_mgr
            resp = client.post(
                "/api/pipeline/start-from-backtest",
                json={
                    "run_config": {
                        "strategy": "cex_dex_arb",
                        "min_spread_bps": 10.0,
                        "fee_bps": 25.0,
                        "position_size_sol": 0.05,
                    },
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "started"
            assert body["mode"] == "paper"
            assert body["strategy"] == "cex_dex_arb"
            # Verify start was called with paper mode
            mock_mgr.start.assert_called_once()
            call_args = mock_mgr.start.call_args
            assert call_args[0][0] == "paper"
            config = call_args[0][1]
            assert config["min_spread_bps"] == 10.0
            assert config["fee_bps"] == 25.0
            assert config["position_size_sol"] == 0.05

    def test_start_from_backtest_error(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.start = AsyncMock(side_effect=RuntimeError("Pipeline already running"))
            mock_cls.get.return_value = mock_mgr
            resp = client.post(
                "/api/pipeline/start-from-backtest",
                json={"run_config": {}},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "error"
            assert "already running" in body["error"]

    def test_start_from_backtest_defaults(self, client: TestClient) -> None:
        """When run_config is empty, defaults should be applied."""
        with patch("mev_kit.ui.routers.pipeline.PipelineManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.start = AsyncMock()
            mock_cls.get.return_value = mock_mgr
            resp = client.post(
                "/api/pipeline/start-from-backtest",
                json={"run_config": {}},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "started"
            assert body["strategy"] == "cex_dex_arb"  # default
            config = mock_mgr.start.call_args[0][1]
            assert config["min_spread_bps"] == 15.0
            assert config["fee_bps"] == 30.0
