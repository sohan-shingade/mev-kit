# mev-kit

Open-source Solana MEV framework for strategy development, backtesting, and execution.

Detect, simulate, backtest, and execute MEV strategies on Solana with a unified pipeline. Same strategy code runs identically in backtest, paper-trade, and live-execution modes.

## What it does

- **5-layer pipeline**: Source → Detector → Simulator → Sink → Monitor
- **Web UI dashboard**: Real-time monitoring, backtesting, strategy editor, data management
- **Multi-venue data**: Binance, Coinbase, Birdeye, Helius, Bybit, Jupiter — auto-merge with lag correction
- **Realistic fill simulation**: Venue-specific fees, AMM slippage, Jito landing rates, two-leg arb modeling
- **Risk analytics**: Sharpe ratio, max drawdown, equity curves, hourly heatmaps, survivorship bias warnings
- **Strategy optimization**: Parameter sweeps, walk-forward validation, result versioning
- **6 example detectors**: CEX-DEX arb, price momentum, spread tracker, multi-pool arb, liquidation, statistical arb

## Quick start

```bash
# Install
pip install -e ".[dev]"

# Launch the web UI
mev-kit ui

# Opens at http://localhost:8080
```

### First backtest (no API keys needed)

1. Go to **Data** tab → Select SOL/USDC → Check **Coinbase** + **Birdeye** → Click **Fetch & Prepare**
2. Go to **Backtest** tab → Select the merged dataset → Pick a strategy → **Run Backtest**
3. View results: P&L, Sharpe ratio, equity curve, hourly heatmap, cost breakdown

### API keys (optional, for more features)

```bash
# Add to .env file:
HELIUS_API_KEY=your-key          # Free at helius.dev — enables paper trading
BIRDEYE_API_KEY=your-key         # Free at birdeye.so — enables historical DEX prices
TARDIS_API_KEY=your-key          # Optional — real L2 order book data
MEV_KIT_WEBHOOK_URL=your-url     # Optional — Slack/Discord alerts
```

## Architecture

```
Source (IngestAdapter) → Detector → Simulator → Sink → Monitor
```

Every layer is a pluggable interface. Free-tier defaults ship with the package. Pro-tier implementations swap in without changing strategy code.

| Layer | Free tier | Pro tier |
|-------|-----------|----------|
| **Source** | Helius WS, Binance WS, Birdeye, Parquet replay | Geyser, Yellowstone gRPC, ShredStream |
| **Detector** | CEX-DEX arb, momentum, spread tracker | Custom strategies via Strategy Editor |
| **Simulator** | Passthrough, FillSimulator (venue-specific) | RPC simulator, forked validator |
| **Sink** | Paper trade (SQLite), Backtest (Parquet) | Jito bundle, multi-path |
| **Monitor** | Prometheus metrics, structured logging | Custom dashboards |

## Web UI

Launch with `mev-kit ui` — a professional trading terminal interface:

- **Dashboard**: Real-time pipeline monitoring with draggable panels
- **Strategies**: Monaco code editor with Python syntax highlighting, validation, fork examples
- **Backtest**: Run strategies against historical data with fill simulation
- **Config**: TOML profile management, API key status
- **Analysis**: Results explorer with charts, trade table, CSV export
- **Data**: Multi-venue data fetching with auto-merge and lag correction
- **Learn**: 6 educational guides on Solana MEV

## Data pipeline

```
Select market → Pick venues → Fetch → Auto-merge → Lag-correct → Backtest-ready
```

Supported venues:
- **Binance** / **Coinbase** / **Bybit** — CEX historical candles (free, no key)
- **Birdeye** — DEX historical prices aggregated across Raydium, Orca, Meteora, Phoenix
- **Helius** — Live on-chain pool state polling
- **Tardis.dev** — L2 order book snapshots for realistic CEX slippage (optional)

## Fill simulation

Backtests model realistic execution per venue:

| Venue | Fee | Slippage model | Landing rate |
|-------|-----|----------------|-------------|
| Raydium AMM | 25 bps | Constant product `dx/(R+dx)` | 40% Jito |
| Orca Whirlpool | 30 bps | CLMM (3x efficiency) | 40% Jito |
| Jupiter | 0 + venue | Aggregated routing (4x eff) | 45% Jito |
| Binance | 10 bps taker | Order book (Almgren-Chriss) | 98% fill |
| Coinbase | 18 bps taker | Order book | 97% fill |

Two-leg modeling for arb strategies. Volume-weighted pool depth. Dynamic landing rates.

## Strategy development

```python
from mev_kit.strategies.base import Detector
from mev_kit.models import Opportunity, Source, StateUpdate

class MyDetector(Detector):
    required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

    async def process(self, update: StateUpdate) -> Opportunity | None:
        # Your detection logic here
        return None

    def hyperparameters(self):
        return {"min_spread_bps": (5.0, 50.0, 5.0)}
```

Enhanced Detector API (inspired by Artemis, Hummingbot, Jesse.trade):
- `required_sources` — declare data feed requirements
- `sync_state()` — one-time initialization
- `before()` / `after()` — per-update lifecycle hooks
- `filters()` — post-detection validation
- `process_batch()` — multi-opportunity per update
- `hyperparameters()` — optimizer-friendly parameter ranges

## CLI

```bash
mev-kit ui                    # Launch web dashboard
mev-kit backtest --config config/free.toml --data ./data/file.parquet
mev-kit paper --config config/free.toml
mev-kit live --config config/free.toml --size 0.01
mev-kit analyze --db ./data/results.db
```

## Tech stack

**Backend**: Python 3.11+, FastAPI, asyncio, Pydantic v2, aiosqlite, Polars, httpx

**Frontend**: React 18, TypeScript, Vite, Tailwind CSS, TradingView Lightweight Charts, Recharts, Monaco Editor

**Solana**: solders, solana-py, websockets (Helius/Binance), Jito bundles

## Project structure

```
src/mev_kit/
├── pipeline/          # Pipeline orchestrator
├── models/            # Pydantic data models
├── adapters/
│   ├── ingest/        # Data source adapters (Helius, Binance, Birdeye, Parquet replay)
│   ├── simulators/    # Fill simulation (passthrough, RPC, venue-specific)
│   └── sinks/         # Execution output (paper trade, backtest, Jito bundle)
├── strategies/        # Detector base class + examples
│   └── examples/      # 6 example detectors
├── utils/             # Precision math, risk metrics, alerts, monitoring
└── ui/                # FastAPI server + React dashboard
    ├── routers/       # API endpoints
    ├── guides/        # Educational markdown content
    └── static/        # Built React app
```

## Testing

```bash
pytest tests/ -v          # 225 tests
ruff check src/ tests/    # Lint
cd ui && npx tsc --noEmit # TypeScript
```

## License

MIT
