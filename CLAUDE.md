# CLAUDE.md — mev-kit

## What this project is

mev-kit is an open-source Python framework for detecting, simulating, backtesting, and executing MEV (Maximal Extractable Value) strategies on Solana. It provides a unified pipeline abstraction over fragmented external services (Helius, Jito, Jupiter, Binance, etc.) so the same strategy code runs identically in backtest, paper-trade, and live-execution modes by swapping adapter implementations.

## Architecture — the 5-layer pipeline

```
Source (IngestAdapter) → Detector → Simulator → Sink → Monitor
```

Every layer is a pluggable interface. Free-tier defaults ship with the package. Pro-tier implementations swap in without changing strategy code.

### Layer 1: IngestAdapter (data in)
- Abstract base: `src/mev_kit/adapters/ingest/base.py`
- Emits `StateUpdate` objects into an async queue
- Free: HeliusWSAdapter, BinanceWSAdapter, JupiterAdapter, ParquetReplayAdapter
- Pro: GeyserAdapter, YellowstoneGRPCAdapter, ShredStreamAdapter

### Layer 2: Detector (opportunity detection)
- Abstract base: `src/mev_kit/strategies/base.py`
- Consumes `StateUpdate`, emits `Opportunity`
- Ships with: CEXDEXArbDetector, SpreadTracker
- Users implement custom detectors against the same interface

### Layer 3: Simulator (pre-execution validation)
- Abstract base: `src/mev_kit/adapters/simulators/base.py`
- Takes `Opportunity`, returns `SimulationResult` (profitable: bool, net_profit, compute_units)
- Free: RPCSimulator (calls simulateTransaction via Helius free tier)
- Pro: LocalValidatorSimulator, ForkedStateSimulator

### Layer 4: Sink (execution output)
- Abstract base: `src/mev_kit/adapters/sinks/base.py`
- Takes validated `Opportunity` + `SimulationResult`, does something with it
- Free: PaperTradeSink (log to SQLite), BacktestSink (log to Parquet)
- Live: JitoBundleSink, DirectTPUSink
- Pro: MultiPathSink (Jito + bloXroute + TPU in parallel)

### Layer 5: Monitor (observability)
- Logs every pipeline event to structured storage
- Optional Prometheus metrics export
- Tracks: detection_rate, sim_success_rate, landing_rate, pnl_per_strategy

## Key design principles

1. **Adapter pattern everywhere.** Every external service is behind an abstract interface. Tests mock the interface, not the service. Swapping Helius for Geyser is a config change, not a rewrite.

2. **Async-first.** All I/O is async (asyncio). The pipeline is an async event loop consuming from adapter queues. This matters because MEV is I/O-bound (waiting for data, waiting for confirmations), not CPU-bound.

3. **Type-safe models.** All inter-layer communication uses Pydantic models defined in `src/mev_kit/models/`. No raw dicts flowing through the pipeline.

4. **Mode-agnostic strategies.** A strategy (Detector) never knows if it's running against live data or historical replay. It receives `StateUpdate` objects and emits `Opportunity` objects. The pipeline handles mode switching.

5. **Simulation gating.** No opportunity reaches a live Sink without passing through a Simulator first. This is enforced at the Pipeline level, not left to individual strategies.

## Tech stack

- Python 3.11+ (async/await, type hints, Pydantic v2)
- asyncio for concurrency
- websockets for WS connections
- httpx for HTTP API calls
- solders for Solana transaction construction
- solana-py for RPC interaction
- pydantic for data models
- SQLite (via aiosqlite) for results storage
- PyArrow + Polars for Parquet I/O
- pytest + pytest-asyncio for testing
- Click for CLI

## File organization

```
mev-kit/
├── CLAUDE.md              ← you are here
├── README.md
├── pyproject.toml
├── config/
│   ├── free.toml          ← free-tier adapter config
│   └── pro.toml           ← pro-tier adapter config
├── src/mev_kit/
│   ├── __init__.py
│   ├── cli.py             ← Click CLI entry point
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── runner.py      ← Pipeline orchestrator
│   ├── models/
│   │   ├── __init__.py
│   │   ├── state.py       ← StateUpdate, PoolState, PriceUpdate
│   │   ├── opportunity.py ← Opportunity, OpportunityType
│   │   └── results.py     ← SimulationResult, ExecutionResult, PaperTradeRecord
│   ├── adapters/
│   │   ├── ingest/
│   │   │   ├── __init__.py
│   │   │   ├── base.py    ← IngestAdapter ABC
│   │   │   ├── helius_ws.py
│   │   │   ├── binance_ws.py
│   │   │   ├── jupiter.py
│   │   │   └── parquet_replay.py
│   │   ├── sinks/
│   │   │   ├── __init__.py
│   │   │   ├── base.py    ← Sink ABC
│   │   │   ├── paper_trade.py
│   │   │   ├── backtest.py
│   │   │   └── jito_bundle.py
│   │   └── simulators/
│   │       ├── __init__.py
│   │       ├── base.py    ← Simulator ABC
│   │       └── rpc_simulator.py
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py        ← Detector ABC
│   │   └── cex_dex_arb.py ← Reference implementation
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       └── config.py      ← TOML config loader
├── tests/
│   ├── unit/
│   │   ├── test_models.py
│   │   ├── test_detector.py
│   │   ├── test_pipeline.py
│   │   └── test_simulator.py
│   └── integration/
│       └── test_helius_adapter.py
├── examples/
│   ├── backtest_arb.py
│   ├── paper_trade.py
│   └── live_micro.py
└── scripts/
    ├── fetch_historical.py    ← Download Raydium pool states to Parquet
    └── analyze_results.py     ← Post-hoc P&L analysis
```

## Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# CLI
mev-kit backtest --config config/free.toml --strategy cex-dex-arb --data ./data/raydium_sol_usdc.parquet
mev-kit paper --config config/free.toml --strategy cex-dex-arb
mev-kit live --config config/free.toml --strategy cex-dex-arb --size 0.01

# Fetch historical data
python scripts/fetch_historical.py --pool SOL/USDC --days 7 --output ./data/
```

## Environment variables

```bash
HELIUS_API_KEY=         # Free tier key from helius.dev
HELIUS_RPC_URL=         # https://mainnet.helius-rpc.com/?api-key=...
SOLANA_RPC_URL=         # Fallback public RPC
BINANCE_WS_URL=         # wss://stream.binance.com:9443/ws (default, no key needed)
JITO_BLOCK_ENGINE_URL=  # https://mainnet.block-engine.jito.wtf (for live mode)
WALLET_KEYPAIR_PATH=    # Path to Solana keypair JSON (for live mode only)
```

## Coding conventions

- All async functions use `async def`, never threads for I/O
- All models are Pydantic BaseModel with strict types
- All adapters inherit from their ABC and implement all abstract methods
- Type hints on every function signature, no `Any` unless unavoidable
- Docstrings on all public methods (Google style)
- Tests mirror source structure: `src/mev_kit/strategies/cex_dex_arb.py` → `tests/unit/test_cex_dex_arb.py`
- No print statements — use structlog logger from `utils/logging.py`
- Config loaded from TOML, never hardcoded values
- All external API calls wrapped in retry logic with exponential backoff

## Current status

Project scaffold created. All abstract interfaces defined. Free-tier adapters need implementation. Reference CEX-DEX arb detector needs implementation. Pipeline runner needs implementation. Tests need writing.

## Priority order for implementation

1. Models (state.py, opportunity.py, results.py) — foundation everything depends on
2. Abstract bases (IngestAdapter, Detector, Simulator, Sink) — interfaces
3. ParquetReplayAdapter — enables backtesting without any external APIs
4. CEXDEXArbDetector — reference strategy
5. BacktestSink — enables end-to-end backtest pipeline
6. Pipeline runner — wires everything together
7. CLI — `mev-kit backtest` command
8. HeliusWSAdapter + BinanceWSAdapter — enables paper trading
9. RPCSimulator — pre-execution validation
10. PaperTradeSink — enables paper trading mode
11. JitoBundleSink — enables live mode
12. Tests for each component
