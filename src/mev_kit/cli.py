"""mev-kit CLI — entry point for all pipeline modes.

Usage:
    mev-kit backtest --config config/free.toml --data ./data/raydium_sol_usdc.parquet
    mev-kit paper --config config/free.toml
    mev-kit live --config config/free.toml --size 0.01
    mev-kit analyze --db ./data/results.db
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import click
import structlog

if TYPE_CHECKING:
    from mev_kit.models import PipelineConfig

logger = structlog.get_logger()


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """mev-kit: Solana MEV research, development, and deployment framework."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


@main.command()
@click.option("--config", "-c", default="config/free.toml", help="Path to TOML config file")
@click.option("--data", "-d", required=True, help="Path to Parquet data file or directory")
@click.option("--output", "-o", default=None, help="Output Parquet path for results")
def backtest(config: str, data: str, output: str | None) -> None:
    """Run a strategy against historical data."""
    asyncio.run(_run_backtest(config, data, output))


@main.command()
@click.option("--config", "-c", default="config/free.toml", help="Path to TOML config file")
def paper(config: str) -> None:
    """Run a strategy in paper-trade mode against live data."""
    asyncio.run(_run_paper(config))


@main.command()
@click.option("--config", "-c", default="config/free.toml", help="Path to TOML config file")
@click.option("--size", "-s", default=0.01, help="Position size in SOL")
def live(config: str, size: float) -> None:
    """Run a strategy with real Jito bundle submission."""
    click.confirm(
        f"⚠️  Live mode with {size} SOL positions. This spends real SOL. Continue?",
        abort=True,
    )
    asyncio.run(_run_live(config, size))


@main.command()
@click.option("--db", default="./data/results.db", help="Path to results database")
def analyze(db: str) -> None:
    """Analyze paper trade or backtest results."""
    asyncio.run(_run_analysis(db))


@main.command()
@click.option("--config-dir", default="config/", help="Config directory")
@click.option("--data-dir", default="./data/", help="Data directory")
@click.option("--host", default="127.0.0.1", help="Server host")
@click.option("--port", "-p", default=8080, help="Server port")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
def ui(config_dir: str, data_dir: str, host: str, port: int, no_open: bool) -> None:
    """Launch the web UI dashboard."""
    import threading
    import webbrowser
    from pathlib import Path

    import uvicorn

    # Load .env file if it exists
    env_path = Path(".env")
    if env_path.exists():
        import os

        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    from mev_kit.ui.server import create_app

    app = create_app(config_dir=config_dir, data_dir=data_dir)

    if not no_open:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    click.echo(f"Starting mev-kit UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


async def _run_backtest(config_path: str, data_path: str, output: str | None) -> None:
    """Execute backtest pipeline."""
    from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
    from mev_kit.adapters.simulators.base import PassthroughSimulator
    from mev_kit.adapters.sinks.paper_trade import BacktestSink
    from mev_kit.pipeline.runner import Pipeline
    from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

    config = _load_config(config_path)

    adapter = ParquetReplayAdapter({"path": data_path, "source_type": "pool"})
    detector = CEXDEXArbDetector({
        "min_spread_bps": config.min_spread_bps,
        "pair": "SOL/USDC",
        "position_size_sol": config.position_size_sol,
    })
    simulator = PassthroughSimulator({})
    sink = BacktestSink({"output_path": output})

    pipeline = Pipeline(
        config=config,
        adapters=[adapter],
        detector=detector,
        simulator=simulator,
        sink=sink,
    )
    await pipeline.run()

    # Print summary
    click.echo(f"\n📊 Backtest complete: {len(sink.results)} opportunities detected")
    if sink.results:
        total = sum(r["estimated_profit_sol"] for r in sink.results)
        click.echo(f"   Total theoretical profit: {total:.6f} SOL")
        avg_spread = sum(r["spread_bps"] for r in sink.results) / len(sink.results)
        click.echo(f"   Avg spread: {avg_spread:.1f} bps")


async def _run_paper(config_path: str) -> None:
    """Execute paper trading pipeline."""
    import os
    import signal

    from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
    from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
    from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
    from mev_kit.adapters.sinks.paper_trade import PaperTradeSink
    from mev_kit.pipeline.runner import Pipeline
    from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

    config = _load_config(config_path)

    # Read API keys from environment
    helius_api_key = os.environ.get("HELIUS_API_KEY", config.helius_api_key)
    helius_rpc_url = os.environ.get("HELIUS_RPC_URL", config.helius_rpc_url)

    if not helius_api_key:
        click.echo("Error: HELIUS_API_KEY environment variable required for paper trading.")
        click.echo("Get a free key at https://helius.dev")
        return

    # Instantiate adapters
    helius_adapter = HeliusWSAdapter({
        "helius_api_key": helius_api_key,
        "helius_ws_url": f"wss://mainnet.helius-rpc.com/?api-key={helius_api_key}",
        "pool_addresses": ["58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"],
        "commitment": "processed",
    })

    binance_adapter = BinanceWSAdapter({
        "symbol": "solusdt",
    })

    detector = CEXDEXArbDetector({
        "min_spread_bps": config.min_spread_bps,
        "fee_bps": 30.0,
        "pair": "SOL/USDC",
        "position_size_sol": config.position_size_sol,
    })

    simulator = RPCSimulator({
        "rpc_url": helius_rpc_url or f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}",
        "tip_percentage": config.tip_percentage,
        "min_tip_lamports": config.min_tip_lamports,
        "max_tip_lamports": config.max_tip_lamports,
    })

    sink = PaperTradeSink({
        "db_path": config.results_db,
    })

    pipeline = Pipeline(
        config=config,
        adapters=[helius_adapter, binance_adapter],
        detector=detector,
        simulator=simulator,
        sink=sink,
    )

    # Handle Ctrl+C gracefully
    loop = asyncio.get_event_loop()

    def _signal_handler() -> None:
        click.echo("\nShutting down paper trading...")
        asyncio.ensure_future(pipeline.stop())

    loop.add_signal_handler(signal.SIGINT, _signal_handler)

    click.echo("Starting paper trading mode...")
    click.echo(f"  Strategy: {config.strategy}")
    click.echo(f"  Min spread: {config.min_spread_bps} bps")
    click.echo(f"  Position size: {config.position_size_sol} SOL")
    click.echo(f"  Results DB: {config.results_db}")
    click.echo("Press Ctrl+C to stop.\n")

    await pipeline.run()

    click.echo("\nPaper trading complete.")
    click.echo(f"  Updates processed: {pipeline.updates_processed}")
    click.echo(f"  Opportunities detected: {pipeline.opportunities_detected}")
    click.echo(f"  Opportunities executed: {pipeline.opportunities_executed}")
    click.echo(f"  Total theoretical P&L: {pipeline.total_profit_sol:.6f} SOL")


async def _run_live(config_path: str, size: float) -> None:
    """Execute live trading pipeline."""
    import os
    import signal

    from mev_kit.adapters.ingest.binance_ws import BinanceWSAdapter
    from mev_kit.adapters.ingest.helius_ws import HeliusWSAdapter
    from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
    from mev_kit.adapters.sinks.jito_bundle import JitoBundleSink
    from mev_kit.models import ExecutionMode
    from mev_kit.pipeline.runner import Pipeline
    from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector

    config = _load_config(config_path)
    config.mode = ExecutionMode.LIVE
    config.position_size_sol = size

    helius_api_key = os.environ.get("HELIUS_API_KEY", config.helius_api_key)
    helius_rpc_url = os.environ.get("HELIUS_RPC_URL", config.helius_rpc_url)
    keypair_path = os.environ.get("WALLET_KEYPAIR_PATH", "")

    if not helius_api_key:
        click.echo("Error: HELIUS_API_KEY required.")
        return
    if not keypair_path:
        click.echo("Error: WALLET_KEYPAIR_PATH required for live mode.")
        return

    helius_adapter = HeliusWSAdapter({
        "helius_api_key": helius_api_key,
        "pool_addresses": ["58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"],
    })
    binance_adapter = BinanceWSAdapter({"symbol": "solusdt"})

    detector = CEXDEXArbDetector({
        "min_spread_bps": config.min_spread_bps,
        "pair": "SOL/USDC",
        "position_size_sol": size,
    })

    simulator = RPCSimulator({
        "rpc_url": helius_rpc_url or f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}",
    })

    sink = JitoBundleSink({
        "jito_url": config.jito_block_engine_url,
        "tip_percentage": config.tip_percentage,
        "min_tip_lamports": config.min_tip_lamports,
        "max_tip_lamports": config.max_tip_lamports,
        "keypair_path": keypair_path,
    })

    pipeline = Pipeline(
        config=config,
        adapters=[helius_adapter, binance_adapter],
        detector=detector,
        simulator=simulator,
        sink=sink,
    )

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(pipeline.stop()))

    click.echo(f"LIVE MODE with {size} SOL positions. Submitting real Jito bundles.")
    await pipeline.run()


async def _run_analysis(db_path: str) -> None:
    """Analyze results from paper trades or backtests."""
    import aiosqlite

    if not Path(db_path).exists():
        click.echo(f"Database not found: {db_path}")
        return

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM paper_trades") as cursor:
            count = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT SUM(simulated_profit_sol), AVG(spread_bps),"
            " MIN(timestamp), MAX(timestamp) FROM paper_trades"
        ) as cursor:
            row = await cursor.fetchone()

    click.echo(f"\n📊 Results from {db_path}")
    click.echo(f"   Trades: {count}")
    if row and row[0]:
        click.echo(f"   Total profit: {row[0]:.6f} SOL")
        click.echo(f"   Avg spread: {row[1]:.1f} bps")
        click.echo(f"   Period: {row[2]} → {row[3]}")


def _load_config(path: str) -> PipelineConfig:
    """Load PipelineConfig from TOML file."""
    from mev_kit.models import PipelineConfig

    try:
        import tomli

        with open(path, "rb") as f:
            raw = tomli.load(f)
    except FileNotFoundError:
        logger.warning("config.not_found", path=path)
        return PipelineConfig()

    # Flatten nested TOML sections
    flat = {}
    for section in raw.values():
        if isinstance(section, dict):
            flat.update(section)
        else:
            flat[str(section)] = section

    return PipelineConfig(**{k: v for k, v in flat.items() if k in PipelineConfig.model_fields})


if __name__ == "__main__":
    main()
