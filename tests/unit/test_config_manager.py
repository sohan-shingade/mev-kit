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
        assert "HELIUS_API_KEY" in status
        assert isinstance(status["HELIUS_API_KEY"], bool)
