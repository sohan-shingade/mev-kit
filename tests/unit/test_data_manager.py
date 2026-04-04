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
