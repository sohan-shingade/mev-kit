"""End-to-end integration test for the web UI API."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import polars as pl
import pytest
from fastapi.testclient import TestClient

from mev_kit.ui.server import create_app


def _create_test_parquet(tmpdir: str) -> str:
    path = os.path.join(tmpdir, "test_data.parquet")
    rows = []
    for i in range(20):
        price = 148.0 if i < 10 else 146.0
        rows.append({
            "pool_address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
            "dex": "raydium",
            "base_mint": "SOL",
            "quote_mint": "USDC",
            "base_reserve": 1000.0,
            "quote_reserve": price * 1000,
            "price": price,
            "fee_bps": 30,
            "slot": 280000000 + i,
            "timestamp": datetime(2024, 1, 15, 12, 0, i, tzinfo=UTC),
        })
    pl.DataFrame(rows).write_parquet(path)
    return path


class TestUIE2E:

    @pytest.fixture
    def env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = _create_test_parquet(tmpdir)
            app = create_app(config_dir="config/", data_dir=tmpdir)
            client = TestClient(app)
            yield {"client": client, "tmpdir": tmpdir, "data_path": data_path}

    def test_pipeline_status_starts_idle(self, env) -> None:
        resp = env["client"].get("/api/pipeline/status")
        assert resp.status_code == 200
        assert resp.json()["state"] == "idle"

    def test_config_profiles_lists_free_and_pro(self, env) -> None:
        resp = env["client"].get("/api/config/profiles")
        assert resp.status_code == 200
        profiles = resp.json()
        assert "free" in profiles
        assert "pro" in profiles

    def test_config_load_free(self, env) -> None:
        resp = env["client"].get("/api/config?profile=free")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"]["min_spread_bps"] == 15.0

    def test_config_env_status(self, env) -> None:
        resp = env["client"].get("/api/config/env")
        assert resp.status_code == 200
        data = resp.json()
        assert "HELIUS_API_KEY" in data

    def test_data_files_lists_parquet(self, env) -> None:
        resp = env["client"].get("/api/data/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 1
        assert files[0]["name"] == "test_data.parquet"
        assert files[0]["rows"] == 20

    def test_data_preview(self, env) -> None:
        resp = env["client"].get("/api/data/files/test_data.parquet/preview?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 5
        assert data["total_rows"] == 20

    def test_docs_guides_lists_five(self, env) -> None:
        resp = env["client"].get("/api/docs/guides")
        assert resp.status_code == 200
        guides = resp.json()
        assert len(guides) == 5

    def test_docs_guide_content(self, env) -> None:
        resp = env["client"].get("/api/docs/guides/01-mev-on-solana")
        assert resp.status_code == 200
        data = resp.json()
        assert "html" in data
        assert "MEV" in data["html"]
