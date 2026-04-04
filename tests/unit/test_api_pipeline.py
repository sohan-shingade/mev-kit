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
            resp = client.post("/api/pipeline/start", json={"mode": "paper", "config": {"min_spread_bps": 20.0}})
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
