"""DataManager — Parquet file CRUD and background fetch jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger()


class DataManager:
    """Manages Parquet data files and fetch jobs."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)

    def list_files(self) -> list[dict[str, Any]]:
        """List Parquet files with metadata."""
        if not self.data_dir.exists():
            return []
        files = []
        for p in sorted(self.data_dir.glob("*.parquet")):
            try:
                df = pl.scan_parquet(p)
                rows = df.select(pl.len()).collect().item()
                cols = df.collect_schema().names()
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
