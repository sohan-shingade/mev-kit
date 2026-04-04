"""Post-hoc analysis of paper trade and backtest results.

Reads the SQLite results database and prints summary statistics:
- Total trades, win rate, total P&L
- Average spread, best/worst trade
- Distribution by hour of day
- Distribution by spread bucket

Usage:
    python scripts/analyze_results.py --db ./data/results.db
    python scripts/analyze_results.py --db ./data/results.db --csv ./data/report.csv
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

import aiosqlite
import click
import structlog

logger = structlog.get_logger()


async def analyze(db_path: str, csv_path: str | None) -> None:
    """Run analysis on the results database."""
    if not Path(db_path).exists():
        click.echo(f"Database not found: {db_path}")
        sys.exit(1)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Summary statistics
        async with db.execute("SELECT COUNT(*) FROM paper_trades") as cur:
            total = (await cur.fetchone())[0]

        if total == 0:
            click.echo("No trades found in database.")
            return

        async with db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(simulated_profit_sol) as total_profit,
                AVG(simulated_profit_sol) as avg_profit,
                MAX(simulated_profit_sol) as best_trade,
                MIN(simulated_profit_sol) as worst_trade,
                AVG(spread_bps) as avg_spread,
                MIN(spread_bps) as min_spread,
                MAX(spread_bps) as max_spread,
                MIN(timestamp) as first_trade,
                MAX(timestamp) as last_trade,
                SUM(CASE WHEN simulated_profit_sol > 0 THEN 1 ELSE 0 END) as winners
            FROM paper_trades
        """) as cur:
            row = await cur.fetchone()

        click.echo("\n" + "=" * 60)
        click.echo("  MEV-KIT RESULTS ANALYSIS")
        click.echo("=" * 60)
        click.echo(f"  Database:     {db_path}")
        click.echo(f"  Period:       {row[8]} to {row[9]}")
        click.echo(f"  Total trades: {row[0]}")
        click.echo(f"  Win rate:     {row[10] / row[0] * 100:.1f}%")
        click.echo(f"  Total P&L:    {row[1]:.6f} SOL")
        click.echo(f"  Avg profit:   {row[2]:.6f} SOL")
        click.echo(f"  Best trade:   {row[3]:.6f} SOL")
        click.echo(f"  Worst trade:  {row[4]:.6f} SOL")
        click.echo(f"  Avg spread:   {row[5]:.1f} bps")
        click.echo(f"  Spread range: {row[6]:.1f} - {row[7]:.1f} bps")

        # Distribution by hour
        click.echo("\n  Opportunities by hour:")
        click.echo("  " + "-" * 40)
        async with db.execute("""
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                COUNT(*) as count,
                SUM(simulated_profit_sol) as profit
            FROM paper_trades
            GROUP BY hour
            ORDER BY hour
        """) as cur:
            async for hrow in cur:
                bar = "#" * min(int(hrow[1] / max(1, total) * 50), 50)
                click.echo(f"  {hrow[0]:02d}:00  {hrow[1]:4d}  {hrow[2]:+.6f} SOL  {bar}")

        # Distribution by spread bucket
        click.echo("\n  Spread distribution:")
        click.echo("  " + "-" * 40)
        async with db.execute("""
            SELECT
                CASE
                    WHEN spread_bps < 20 THEN '  0-20 bps'
                    WHEN spread_bps < 50 THEN ' 20-50 bps'
                    WHEN spread_bps < 100 THEN ' 50-100 bps'
                    WHEN spread_bps < 200 THEN '100-200 bps'
                    ELSE '200+ bps'
                END as bucket,
                COUNT(*) as count,
                AVG(simulated_profit_sol) as avg_profit
            FROM paper_trades
            GROUP BY bucket
            ORDER BY bucket
        """) as cur:
            async for srow in cur:
                click.echo(f"  {srow[0]}:  {srow[1]:4d} trades  avg {srow[2]:.6f} SOL")

        # Distribution by direction
        click.echo("\n  By direction:")
        click.echo("  " + "-" * 40)
        async with db.execute("""
            SELECT direction, COUNT(*), SUM(simulated_profit_sol)
            FROM paper_trades GROUP BY direction
        """) as cur:
            async for drow in cur:
                click.echo(f"  {drow[0]:10s}  {drow[1]:4d} trades  {drow[2]:+.6f} SOL")

        # Export to CSV
        if csv_path:
            async with db.execute("SELECT * FROM paper_trades ORDER BY timestamp") as cur:
                rows = await cur.fetchall()
                columns = [d[0] for d in cur.description]

            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(rows)

            click.echo(f"\n  Exported {len(rows)} rows to {csv_path}")

        click.echo("")


@click.command()
@click.option("--db", default="./data/results.db", help="Path to results database")
@click.option("--csv", "csv_path", default=None, help="Export results to CSV")
def main(db: str, csv_path: str | None) -> None:
    """Analyze paper trade or backtest results."""
    asyncio.run(analyze(db, csv_path))


if __name__ == "__main__":
    main()
