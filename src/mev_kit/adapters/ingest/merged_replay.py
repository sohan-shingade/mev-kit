"""Merged replay adapter -- replays time-aligned DEX + CEX data.

Reads a merged Parquet file (produced by data_prep.prepare_backtest_data)
and emits alternating DEX and CEX StateUpdates in strict time order.
This ensures deterministic, bias-free backtesting.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import polars as pl

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.models import PoolState, PriceUpdate, Source, StateUpdate


class MergedReplayAdapter(IngestAdapter):
    """Replays merged DEX+CEX data with strict time ordering.

    For each row in the merged dataset, emits:
    1. A DEX StateUpdate (Source.PARQUET_REPLAY, PoolState with dex_price)
    2. A CEX StateUpdate (Source.BINANCE_WS, PriceUpdate with cex_price)

    This guarantees that the detector always sees both prices from
    the same timestamp before processing the next timestamp.
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.path = config.get("path", "")
        self._df: pl.DataFrame | None = None

    async def connect(self) -> None:
        """Load the merged Parquet file into memory."""
        self._df = pl.read_parquet(self.path)

    async def disconnect(self) -> None:
        """Release the dataframe."""
        self._df = None

    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Yield paired DEX + CEX StateUpdates in strict time order."""
        if self._df is None:
            raise RuntimeError("Adapter not connected. Call connect() first.")

        for row in self._df.iter_rows(named=True):
            if not self._running:
                break

            ts = row.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif ts is None:
                continue

            dex_price = float(row.get("dex_price", 0))
            cex_price = float(row.get("cex_price", 0))

            if dex_price <= 0 or cex_price <= 0:
                continue

            # Emit DEX update first
            pool = PoolState(
                pool_address=str(row.get("pool_address", "merged_backtest")),
                dex=str(row.get("dex", "aggregated")),
                base_mint=str(
                    row.get(
                        "base_mint",
                        "So11111111111111111111111111111111111111112",
                    )
                ),
                quote_mint=str(
                    row.get(
                        "quote_mint",
                        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    )
                ),
                base_reserve=float(row.get("base_reserve", 0)),
                quote_reserve=float(row.get("quote_reserve", 0)),
                price=dex_price,
                fee_bps=int(row.get("fee_bps", 30)),
                slot=int(row.get("slot", 0)),
                timestamp=ts,
            )
            yield StateUpdate(source=Source.PARQUET_REPLAY, pool=pool)

            # Then emit CEX update
            price = PriceUpdate(
                symbol=str(row.get("symbol", "SOL/USDC")),
                price=cex_price,
                volume=None,
                source=Source.BINANCE_WS,
                timestamp=ts,
            )
            yield StateUpdate(source=Source.BINANCE_WS, price=price)
