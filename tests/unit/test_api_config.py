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
