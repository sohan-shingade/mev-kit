"""Backtest data preparation -- merge, align, and validate DEX + CEX datasets.

Eliminates lookahead bias and ensures time synchronization for
honest backtesting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import structlog

logger = structlog.get_logger()


def prepare_backtest_data(
    dex_path: str,
    cex_path: str,
    output_path: str,
    interval_seconds: int = 60,
    price_column: str = "close",
    lag: bool = True,
    orderbook_path: str | None = None,
) -> dict[str, Any]:
    """Merge DEX and CEX data into a time-aligned backtest dataset.

    Produces a single Parquet file with both prices at each timestamp,
    ensuring:
    1. Strict time alignment (inner join on rounded timestamp)
    2. No lookahead bias (uses lagged prices when lag=True)
    3. Deterministic ordering (sorted by timestamp)
    4. Data quality validation (overlap check, gap detection)

    Args:
        dex_path: Path to DEX Parquet (Birdeye format with 'price' column).
        cex_path: Path to CEX Parquet (Binance format with 'close' column).
        output_path: Where to write the merged Parquet.
        interval_seconds: Expected candle interval for rounding.
        price_column: Which candle price to use.
        lag: If True, shift prices by 1 row to prevent lookahead.
        orderbook_path: Optional path to an order book Parquet (Tardis/Kaiko
            format).  When provided, book metrics (spread, depth) are joined
            onto each row so FillSimulator can use real L2 data instead of
            estimates.

    Returns:
        Dict with merge statistics (rows, overlap, gaps, etc.).
    """
    # Load both datasets
    dex_df = pl.read_parquet(dex_path)
    cex_df = pl.read_parquet(cex_path)

    # Normalize timestamps to the nearest interval boundary
    # This ensures alignment even if sources have slight offsets
    dex_df = dex_df.with_columns(
        pl.col("timestamp").dt.truncate(f"{interval_seconds}s").alias("ts_aligned")
    )

    # For CEX data, determine the price column
    if "close" in cex_df.columns:
        cex_price_col = "close"
    elif "price" in cex_df.columns:
        cex_price_col = "price"
    else:
        msg = f"CEX data has no 'close' or 'price' column. Columns: {cex_df.columns}"
        raise ValueError(msg)

    cex_df = cex_df.with_columns(
        pl.col("timestamp").dt.truncate(f"{interval_seconds}s").alias("ts_aligned"),
        pl.col(cex_price_col).alias("cex_price"),
    )

    # Extract DEX price
    if "price" in dex_df.columns:
        dex_df = dex_df.with_columns(pl.col("price").alias("dex_price"))
    else:
        msg = f"DEX data has no 'price' column. Columns: {dex_df.columns}"
        raise ValueError(msg)

    # Deduplicate: if multiple rows per interval, take the last one (most recent)
    dex_dedup = (
        dex_df.group_by("ts_aligned")
        .agg(pl.col("dex_price").last())
        .sort("ts_aligned")
    )

    cex_dedup = (
        cex_df.group_by("ts_aligned")
        .agg(pl.col("cex_price").last())
        .sort("ts_aligned")
    )

    # Inner join on aligned timestamp -- only keep rows where both have data
    merged = dex_dedup.join(cex_dedup, on="ts_aligned", how="inner").sort("ts_aligned")

    if len(merged) == 0:
        return {
            "error": "No overlapping timestamps between DEX and CEX data",
            "dex_range": f"{dex_df['timestamp'].min()} to {dex_df['timestamp'].max()}",
            "cex_range": f"{cex_df['timestamp'].min()} to {cex_df['timestamp'].max()}",
            "rows": 0,
        }

    # Apply lag to prevent lookahead bias
    # At time T, you only know the price from the PREVIOUS candle (T - interval)
    if lag:
        merged = merged.with_columns(
            pl.col("dex_price").shift(1).alias("dex_price"),
            pl.col("cex_price").shift(1).alias("cex_price"),
        ).drop_nulls()  # First row has no previous price

    # Compute spread for validation
    merged = merged.with_columns(
        (
            (pl.col("cex_price") - pl.col("dex_price")).abs()
            / pl.col("cex_price")
            * 10000
        ).alias("spread_bps")
    )

    # Optionally merge order book data for realistic CEX slippage
    ob_stats: dict[str, Any] = {}
    if orderbook_path:
        try:
            ob_df = pl.read_parquet(orderbook_path)
            ob_df = ob_df.with_columns(
                pl.col("timestamp").dt.truncate(f"{interval_seconds}s").alias("ts_aligned")
            ).group_by("ts_aligned").agg(
                pl.col("spread_bps").mean().alias("book_spread_bps"),
                pl.col("bid_depth").mean().alias("book_bid_depth"),
                pl.col("ask_depth").mean().alias("book_ask_depth"),
                pl.col("mid_price").last().alias("book_mid_price"),
            )
            merged = merged.join(ob_df, on="ts_aligned", how="left")
            ob_stats["orderbook_joined"] = True
            ob_stats["orderbook_rows_matched"] = int(
                merged["book_spread_bps"].drop_nulls().len()
            )
        except Exception as exc:
            logger.warning("data_prep.orderbook_join_failed", error=str(exc))
            ob_stats["orderbook_joined"] = False
            ob_stats["orderbook_error"] = str(exc)

    # Build the output in the format ParquetReplayAdapter expects for "pool" type
    # This creates a unified dataset that the backtest runner can use with a SINGLE adapter
    # Include book columns when they are present (from the optional orderbook join above)
    base_select = [
        pl.col("ts_aligned").alias("timestamp"),
        pl.col("dex_price"),
        pl.col("cex_price"),
        pl.col("spread_bps"),
        # Pool-compatible columns for the DEX side
        pl.lit("merged_backtest").alias("pool_address"),
        pl.lit("aggregated").alias("dex"),
        pl.lit("So11111111111111111111111111111111111111112").alias("base_mint"),
        pl.lit("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").alias("quote_mint"),
        pl.lit(0.0).alias("base_reserve"),
        pl.lit(0.0).alias("quote_reserve"),
        pl.col("dex_price").alias("price"),  # ParquetReplayAdapter reads this
        pl.lit(30).alias("fee_bps"),
        pl.lit(0).alias("slot"),
        # CEX columns for the price side
        pl.lit("SOL/USDC").alias("symbol"),
        pl.col("cex_price").alias("cex_close"),
    ]

    # Append book columns when available so FillSimulator can read real L2 data
    if "book_spread_bps" in merged.columns:
        base_select += [
            pl.col("book_spread_bps"),
            pl.col("book_bid_depth"),
            pl.col("book_ask_depth"),
            pl.col("book_mid_price"),
        ]

    output_df = merged.select(base_select)

    # Write output
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    output_df.write_parquet(output_path)

    # Compute stats
    time_range = merged["ts_aligned"].max() - merged["ts_aligned"].min()
    expected_rows = (
        int(time_range.total_seconds() / interval_seconds) + 1 if time_range else 0
    )
    actual_rows = len(merged)
    gap_pct = round((1 - actual_rows / max(1, expected_rows)) * 100, 1)

    stats: dict[str, Any] = {
        "rows": actual_rows,
        "time_range_start": str(merged["ts_aligned"].min()),
        "time_range_end": str(merged["ts_aligned"].max()),
        "dex_price_range": (
            f"{merged['dex_price'].min():.2f} - {merged['dex_price'].max():.2f}"
        ),
        "cex_price_range": (
            f"{merged['cex_price'].min():.2f} - {merged['cex_price'].max():.2f}"
        ),
        "avg_spread_bps": round(float(merged["spread_bps"].mean()), 1),
        "max_spread_bps": round(float(merged["spread_bps"].max()), 1),
        "data_gaps_pct": gap_pct,
        "lag_applied": lag,
        "output_path": output_path,
        **ob_stats,
    }

    logger.info("data_prep.merged", **stats)
    return stats
