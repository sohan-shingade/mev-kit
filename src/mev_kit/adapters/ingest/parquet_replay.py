"""Parquet replay adapter — enables backtesting with zero API calls.

Reads historical state snapshots from Parquet files and replays them
as StateUpdate objects. The detector processes them exactly as it
would live data.

This is the most important adapter for development because it's
completely free and runs at maximum speed (limited only by CPU).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import polars as pl

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.models import PoolState, PriceUpdate, Source, StateUpdate


class ParquetReplayAdapter(IngestAdapter):
    """Replays historical data from Parquet files as StateUpdate stream.

    Config keys:
        path (str): Path to Parquet file or directory of Parquet files.
        speed_multiplier (float): Replay speed. 1.0 = real-time, 0 = as fast as possible. Default: 0
        source_type (str): "pool" or "price". Determines how rows are parsed. Default: "pool"
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.path = config.get("path", "")
        self.speed_multiplier = config.get("speed_multiplier", 0)
        self.source_type = config.get("source_type", "pool")
        # Override the source tag (e.g., BINANCE_WS for CEX replay data)
        source_override = config.get("source_override")
        self._source = Source(source_override) if source_override else Source.PARQUET_REPLAY
        self._df: pl.DataFrame | None = None

    async def connect(self) -> None:
        """Load Parquet file(s) into memory."""
        p = Path(self.path)
        if p.is_dir():
            # Read all parquet files in directory
            frames = []
            for f in sorted(p.glob("*.parquet")):
                frames.append(pl.read_parquet(f))
            if frames:
                self._df = pl.concat(frames)
            else:
                raise FileNotFoundError(f"No Parquet files found in {self.path}")
        elif p.is_file():
            self._df = pl.read_parquet(self.path)
        else:
            raise FileNotFoundError(f"Path not found: {self.path}")

    async def disconnect(self) -> None:
        self._df = None

    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Iterate through Parquet rows, yielding StateUpdate for each."""
        if self._df is None:
            raise RuntimeError("Adapter not connected. Call connect() first.")

        for row in self._df.iter_rows(named=True):
            if not self._running:
                break

            update = self._row_to_update(row)
            if update:
                yield update

    def _row_to_update(self, row: dict) -> StateUpdate | None:
        """Convert a Parquet row to a StateUpdate.

        Expected columns for pool data:
            pool_address, dex, base_mint, quote_mint,
            base_reserve, quote_reserve, price, slot, timestamp

        Expected columns for price data:
            symbol, price, source, timestamp
        """
        try:
            if self.source_type == "pool":
                pool = PoolState(
                    pool_address=str(row.get("pool_address", "")),
                    dex=str(row.get("dex", "unknown")),
                    base_mint=str(row.get("base_mint", "")),
                    quote_mint=str(row.get("quote_mint", "")),
                    base_reserve=float(row.get("base_reserve", 0)),
                    quote_reserve=float(row.get("quote_reserve", 0)),
                    price=float(row.get("price", 0)),
                    fee_bps=int(row.get("fee_bps", 30)),
                    slot=int(row.get("slot", 0)),
                    timestamp=_parse_timestamp(row.get("timestamp")),
                )
                return StateUpdate(source=self._source, pool=pool)

            elif self.source_type == "price":
                price = PriceUpdate(
                    symbol=str(row.get("symbol", "")),
                    price=float(row.get("price", 0)),
                    volume=row.get("volume"),
                    source=self._source,
                    timestamp=_parse_timestamp(row.get("timestamp")),
                )
                return StateUpdate(source=self._source, price=price)

        except (ValueError, KeyError, TypeError):
            return None

        return None


def _parse_timestamp(val: object) -> datetime:
    """Parse various timestamp formats to datetime."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        # Assume Unix timestamp (seconds or milliseconds)
        if val > 1e12:
            return datetime.utcfromtimestamp(val / 1000)
        return datetime.utcfromtimestamp(val)
    if isinstance(val, str):
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    return datetime.utcnow()
