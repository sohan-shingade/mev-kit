<p align="center">
  <br/>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://img.shields.io/badge/MEV--KIT-Solana_MEV_Framework-e24b4a?style=for-the-badge&labelColor=09090b">
    <img alt="MEV-Kit" src="https://img.shields.io/badge/MEV--KIT-Solana_MEV_Framework-e24b4a?style=for-the-badge&labelColor=09090b">
  </picture>
  <br/><br/>
  <strong>Open-source framework for building, backtesting, and paper-trading MEV strategies on Solana.</strong>
  <br/>
  <em>Pluggable pipeline | realistic fill simulation | web UI with strategy editor | MIT</em>
  <br/><br/>
  <a href="#quick-start"><img src="https://img.shields.io/badge/setup-1_command-57c84d?style=flat-square&labelColor=141418" alt="1 command"></a>
  <img src="https://img.shields.io/badge/detectors-7_built--in-e24b4a?style=flat-square&labelColor=141418" alt="7 detectors">
  <img src="https://img.shields.io/badge/tests-256-22c55e?style=flat-square&labelColor=141418" alt="256 tests">
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&labelColor=141418" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-gray?style=flat-square&labelColor=141418" alt="MIT License">
</p>

---

> **Status: Alpha (v0.1.0)** -- Research and paper-trading toolkit. Live execution builds real Solana transactions via `solders` for known pools (SOL/USDC Raydium). Not yet mainnet-validated for production use.

---

## What This Is

MEV-Kit is a Python framework for detecting, simulating, and executing Maximal Extractable Value strategies on Solana. The architecture follows a 5-layer pluggable pipeline where the same strategy code runs identically in backtest, paper-trade, and live-execution modes by swapping adapter implementations.

It ships with a professional web UI (React + FastAPI), 7 built-in detectors, multi-venue data ingestion, and a fill simulator that models adverse selection, volume-based order book depth, and spread-proportional staleness decay.

---

## Architecture

```
Source (IngestAdapter) --> Detector --> Simulator --> Sink --> Monitor
```

Every layer is a pluggable interface. Free-tier defaults ship with the package. Pro-tier implementations swap in without changing strategy code.

| Layer | Free Tier | Pro Tier |
|-------|-----------|----------|
| **Source** | Helius WS, Binance WS, Coinbase WS, Birdeye, Parquet replay | Geyser, Yellowstone gRPC, ShredStream |
| **Detector** | CEX-DEX arb, momentum, spread tracker, + 4 more | Custom strategies via Strategy Editor |
| **Simulator** | Passthrough, FillSimulator (adverse selection + volume depth) | RPC simulator, forked validator |
| **Sink** | Paper trade (SQLite), Backtest (Parquet) | Jito bundle, multi-path |
| **Monitor** | Prometheus metrics, structured logging | Custom dashboards |

---

## Quick Start

```bash
pip install -e ".[dev]"
mev-kit ui
# Opens at http://localhost:8080
```

### First Backtest (no API keys needed)

1. **Data** tab -- Select SOL/USDC, check Coinbase + Birdeye, click Fetch & Prepare
2. **Backtest** tab -- Select the merged dataset, pick a strategy, click Run Backtest
3. **Analysis** tab -- View P&L, Sharpe ratio, equity curve, hourly heatmap, cost breakdown

### Optional API Keys

```bash
# .env file:
HELIUS_API_KEY=your-key          # Free at helius.dev -- enables paper trading
BIRDEYE_API_KEY=your-key         # Free at birdeye.so -- enables historical DEX prices
TARDIS_API_KEY=your-key          # Optional -- real L2 order book data
MEV_KIT_WEBHOOK_URL=your-url     # Optional -- Slack/Discord alerts
```

---

## Web UI

Launch with `mev-kit ui` -- a terminal-style trading interface with 7 panels:

| Panel | What It Does |
|-------|--------------|
| **Dashboard** | Real-time pipeline monitoring with draggable panels |
| **Strategies** | Monaco code editor with Python syntax highlighting, validation, fork examples |
| **Backtest** | Run strategies against historical data with fill simulation |
| **Analysis** | Results explorer with charts, trade table, CSV export |
| **Data** | Multi-venue data fetching with auto-merge and lag correction |
| **Config** | TOML profile management, API key status |
| **Learn** | 6 educational guides on Solana MEV |

---

## Data Pipeline

```
Select market --> Pick venues --> Fetch --> Auto-merge --> Lag-correct --> Backtest-ready
```

| Venue | Type | Key Required |
|-------|------|--------------|
| **Binance** | CEX historical candles + live WebSocket trades | No |
| **Coinbase** | CEX historical candles + live WebSocket trades | No |
| **Bybit** | CEX historical candles | No |
| **Birdeye** | DEX prices aggregated across Raydium, Orca, Meteora, Phoenix | Yes (free) |
| **Helius** | Live on-chain pool state polling | Yes (free) |
| **Tardis.dev** | L2 order book snapshots for realistic CEX slippage | Yes (optional) |

---

## Fill Simulation

Backtests model realistic execution with three layers of realism per venue:

| Venue | Fee | Slippage Model | Landing Rate |
|-------|-----|----------------|-------------|
| Raydium AMM | 25 bps | Constant product `dx/(R+dx)` | 40% Jito |
| Orca Whirlpool | 30 bps | CLMM (3x efficiency) | 40% Jito |
| Jupiter | 0 + venue | Aggregated routing (4x eff) | 45% Jito |
| Binance | 10 bps taker | Order book (Almgren-Chriss) | 98% fill |
| Coinbase | 18 bps taker | Order book | 97% fill |

**Realism features:**
- **Adverse selection** -- ~55-80% of fills experience spread reversion before execution (breaks the artificial 100% win rate)
- **Volume-based depth** -- Order book depth estimated from CEX candle volume (~1% of daily volume within 10 bps), not hardcoded
- **Spread-proportional staleness** -- Large spreads (30+ bps) decay 60-80%/sec as competition closes them; small spreads persist
- **Two-leg arb modeling** -- Separate cost simulation for DEX and CEX legs
- **Dynamic landing rates** -- Competition-adjusted Jito bundle landing probability

---

## Strategy Development

Strategies are Python classes that implement the `Detector` interface. Return an `Opportunity`, or `None`.

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

### Detector API

Inspired by Artemis, Hummingbot, and Jesse.trade:

| Method | Purpose |
|--------|---------|
| `required_sources` | Declare data feed requirements |
| `sync_state()` | One-time initialization |
| `before()` / `after()` | Per-update lifecycle hooks |
| `filters()` | Post-detection validation |
| `process_batch()` | Multi-opportunity per update |
| `hyperparameters()` | Optimizer-friendly parameter ranges |

### Built-in Detectors

1. CEX-DEX arbitrage
2. Price momentum
3. Spread tracker
4. Multi-pool arbitrage
5. Liquidation detector
6. Statistical arbitrage
7. Volatility regime spread

---

## CLI

```bash
mev-kit ui                    # Launch web dashboard
mev-kit backtest --config config/free.toml --data ./data/file.parquet
mev-kit paper --config config/free.toml
mev-kit live --config config/free.toml --size 0.01
mev-kit analyze --db ./data/results.db
```

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python 3.11+, FastAPI, asyncio, Pydantic v2, aiosqlite, Polars, httpx |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS, TradingView Lightweight Charts, Recharts, Monaco Editor |
| **Solana** | solders, solana-py, websockets (Helius/Binance/Coinbase), Jito bundles |
| **Testing** | pytest, pytest-asyncio, ruff |

---

## Project Structure

```
mev-kit/
├── src/mev_kit/
│   ├── cli.py                 # Click CLI entry point
│   ├── pipeline/
│   │   └── runner.py          # Pipeline orchestrator
│   ├── models/
│   │   ├── state.py           # StateUpdate, PoolState, PriceUpdate
│   │   ├── opportunity.py     # Opportunity, OpportunityType
│   │   └── results.py         # SimulationResult, ExecutionResult
│   ├── adapters/
│   │   ├── ingest/            # Data sources: Helius, Binance, Coinbase, Birdeye, Parquet replay
│   │   ├── simulators/        # Fill simulation: passthrough, RPC, venue-specific
│   │   └── sinks/             # Execution: paper trade, backtest, Jito bundle
│   ├── strategies/
│   │   ├── base.py            # Detector ABC
│   │   ├── cex_dex_arb.py     # Reference implementation
│   │   └── examples/          # 6 example detectors
│   ├── utils/                 # Precision math, risk metrics, alerts
│   └── ui/
│       ├── server.py          # FastAPI server
│       ├── routers/           # API endpoints
│       ├── guides/            # Educational markdown content
│       └── static/            # Built React app
├── config/
│   ├── free.toml              # Free-tier adapter config
│   └── pro.toml               # Pro-tier adapter config
├── tests/                     # 256 tests (unit + integration)
├── examples/                  # backtest_arb.py, paper_trade.py, live_micro.py
└── scripts/                   # Data fetching, analysis, mainnet test
```

---

## Testing

```bash
pytest tests/ -v              # 256 tests
ruff check src/ tests/        # Lint
cd ui && npx tsc --noEmit     # TypeScript type check
```

---

## Current Limitations

| Area | Status | Notes |
|------|--------|-------|
| Backtesting | Working | Fill simulation uses estimated pool depth, not real on-chain reserves |
| Paper trading | Working (with keys) | Requires Helius + Binance/Coinbase WebSocket connections |
| Live execution | Working for SOL/USDC | Real `solders`-built, keypair-signed transactions for Raydium AMM v4 |
| RPC simulation | Working for known pools | Builds real swap transactions, submits to `simulateTransaction` |
| Fill accuracy | ~1.5-3x of reality | Directionally correct; statistical models, not tick-level replay |

### Roadmap

- [x] Real Solana transaction construction via `solders` + Jito bundle submission
- [x] RPC simulator with real transaction construction + `simulateTransaction`
- [x] Calibrated fill simulation (adverse selection, volume-based depth, spread decay)
- [x] Dynamic CLI strategy selection
- [x] Coinbase live WebSocket adapter
- [x] End-to-end mainnet test script (`--dry-run`)
- [ ] Tardis L2 snapshots wired into backtest flow for data-driven adverse selection
- [ ] Tick-level replay with actual order book state per timestamp

---

## License

MIT
