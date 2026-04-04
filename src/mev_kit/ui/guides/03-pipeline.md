# The mev-kit Pipeline

## Overview

mev-kit organizes every strategy into a five-layer pipeline. Each layer is a pluggable interface — you can swap implementations without touching strategy code. The same `CEXDEXArbDetector` runs identically against live Raydium data, a paper-trading feed, or a Parquet file of historical pool states.

```
┌─────────────────────────────────────────────────────────────────┐
│                       mev-kit Pipeline                          │
│                                                                 │
│   ┌──────────┐   StateUpdate   ┌──────────┐   Opportunity       │
│   │  Source  │ ──────────────► │ Detector │ ───────────────►    │
│   │(Ingest   │                 │          │                     │
│   │ Adapter) │                 └──────────┘                     │
│   └──────────┘                       │                          │
│        │                             │ Opportunity              │
│        │                             ▼                          │
│        │                    ┌─────────────────┐                 │
│        │                    │    Simulator    │                 │
│        │                    │ (validates txn) │                 │
│        │                    └────────┬────────┘                 │
│        │                             │                          │
│        │                    SimulationResult                    │
│        │                             │                          │
│        │                             ▼                          │
│        │                       ┌──────────┐                     │
│        │                       │   Sink   │                     │
│        │                       │(execute /│                     │
│        │                       │  log it) │                     │
│        │                       └──────────┘                     │
│        │                             │                          │
│        └─────────────────────────────┴──► Monitor               │
└─────────────────────────────────────────────────────────────────┘
```

Data flows left-to-right and top-to-bottom. Every arrow carries a typed Pydantic model — no raw dicts cross layer boundaries.

---

## Layer 1: IngestAdapter (Source)

**Abstract base**: `src/mev_kit/adapters/ingest/base.py`

The IngestAdapter is responsible for connecting to one or more external data sources and emitting `StateUpdate` objects into an async queue that the rest of the pipeline consumes.

### What a StateUpdate contains

`StateUpdate` (defined in `src/mev_kit/models/state.py`) is a union type. It can carry:

- `PriceUpdate` — a new price tick from a CEX (e.g., Binance SOL/USDC)
- `PoolState` — the current reserve state of a DEX pool (e.g., Raydium SOL/USDC)
- `AccountUpdate` — a generic Solana account data change

```python
from mev_kit.models.state import StateUpdate, PriceUpdate, PoolState

# Example: a PriceUpdate emitted by BinanceWSAdapter
update = PriceUpdate(
    source="binance",
    symbol="SOLUSDC",
    bid=180.45,
    ask=180.47,
    timestamp_ms=1712345678901,
)
```

### Available IngestAdapters

| Adapter | Class | Data Source | Tier |
|---|---|---|---|
| `HeliusWSAdapter` | `adapters/ingest/helius_ws.py` | Helius Enhanced WebSocket | Free |
| `BinanceWSAdapter` | `adapters/ingest/binance_ws.py` | Binance book ticker stream | Free |
| `JupiterAdapter` | `adapters/ingest/jupiter.py` | Jupiter price API | Free |
| `ParquetReplayAdapter` | `adapters/ingest/parquet_replay.py` | Local Parquet files | Free |
| `GeyserAdapter` | *(pro)* | Triton/Helius Geyser gRPC | Pro |
| `YellowstoneGRPCAdapter` | *(pro)* | Yellowstone gRPC | Pro |
| `ShredStreamAdapter` | *(pro)* | Jito ShredStream | Pro |

For backtesting, `ParquetReplayAdapter` reads historical pool states and price ticks from local Parquet files, replaying them at the original timestamps (or accelerated). This adapter is what makes backtesting possible without any external API calls.

### The IngestAdapter interface

```python
from abc import ABC, abstractmethod
from asyncio import Queue
from mev_kit.models.state import StateUpdate

class IngestAdapter(ABC):
    @abstractmethod
    async def start(self, queue: Queue[StateUpdate]) -> None:
        """Connect to the data source and begin emitting StateUpdates into queue."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Cleanly disconnect from the data source."""
        ...
```

---

## Layer 2: Detector (Opportunity Detection)

**Abstract base**: `src/mev_kit/strategies/base.py`

The Detector consumes `StateUpdate` objects one at a time and decides whether to emit an `Opportunity`. It maintains whatever internal state it needs (e.g., the last seen CEX price).

```python
from abc import ABC, abstractmethod
from mev_kit.models.state import StateUpdate
from mev_kit.models.opportunity import Opportunity

class Detector(ABC):
    @abstractmethod
    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a single StateUpdate. Return an Opportunity or None."""
        ...
```

A Detector that returns `None` means "no opportunity detected in this update." Returning an `Opportunity` triggers the Simulator.

### What an Opportunity contains

`Opportunity` (defined in `src/mev_kit/models/opportunity.py`) carries:

- `opportunity_type`: `CEX_DEX_ARB_BUY` or `CEX_DEX_ARB_SELL` (or other strategy types)
- `pool_address`: the Raydium pool address
- `cex_price`, `dex_price`: the prices at detection time
- `spread_bps`, `net_spread_bps`: gross and net spreads
- `estimated_profit_usd`: estimated gross profit
- `position_size_usd`: intended trade size
- `detected_at_ms`: timestamp for latency tracking

### The reference Detector: CEXDEXArbDetector

`src/mev_kit/strategies/cex_dex_arb.py` implements the spread-based arb logic described in [Guide 2](./02-cex-dex-arb.md). It maintains a two-sided state: the latest CEX price and the latest DEX pool state. When both sides are fresh and the spread exceeds `min_spread_bps`, it emits an `Opportunity`.

---

## Layer 3: Simulator (Pre-execution Validation)

**Abstract base**: `src/mev_kit/adapters/simulators/base.py`

The Simulator takes an `Opportunity` and validates it by constructing the swap transaction and simulating it against current on-chain state. It returns a `SimulationResult`.

```python
from abc import ABC, abstractmethod
from mev_kit.models.opportunity import Opportunity
from mev_kit.models.results import SimulationResult

class Simulator(ABC):
    @abstractmethod
    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        """Simulate the opportunity. Returns SimulationResult with profitable flag."""
        ...
```

`SimulationResult` carries:
- `profitable: bool` — the gate flag; only `True` results proceed to the Sink
- `net_profit_usd`: refined profit estimate after simulation
- `compute_units`: estimated compute units for the transaction
- `simulation_error: str | None`: error message if simulation failed

### Simulation gating is enforced at the Pipeline level

The `PipelineRunner` in `src/mev_kit/pipeline/runner.py` enforces that no `Opportunity` reaches a live `Sink` without a passing `SimulationResult`. This is not optional and cannot be bypassed by individual strategies.

### Available Simulators

| Simulator | Class | Backend | Tier |
|---|---|---|---|
| `RPCSimulator` | `adapters/simulators/rpc_simulator.py` | Helius `simulateTransaction` | Free |
| `LocalValidatorSimulator` | *(pro)* | Local `solana-test-validator` fork | Pro |
| `ForkedStateSimulator` | *(pro)* | In-memory forked state | Pro |

`RPCSimulator` calls the Solana JSON-RPC `simulateTransaction` method. It is free (using your Helius API key) but adds ~50–150ms of latency per opportunity. This makes it unsuitable for live trading at the tightest spreads, but perfectly adequate for paper trading and backtesting.

---

## Layer 4: Sink (Execution Output)

**Abstract base**: `src/mev_kit/adapters/sinks/base.py`

The Sink receives a validated `(Opportunity, SimulationResult)` pair and takes action — executing a trade, logging to a database, writing to a file, or printing to the console.

```python
from abc import ABC, abstractmethod
from mev_kit.models.opportunity import Opportunity
from mev_kit.models.results import SimulationResult

class Sink(ABC):
    @abstractmethod
    async def send(
        self,
        opportunity: Opportunity,
        simulation: SimulationResult,
    ) -> None:
        """Handle a validated opportunity."""
        ...
```

### Available Sinks

| Sink | Class | Behavior | Use Case |
|---|---|---|---|
| `PaperTradeSink` | `adapters/sinks/paper_trade.py` | Log to SQLite, no real txns | Paper trading |
| `BacktestSink` | `adapters/sinks/backtest.py` | Log to Parquet | Backtesting |
| `JitoBundleSink` | `adapters/sinks/jito_bundle.py` | Submit Jito bundle | Live trading |
| `DirectTPUSink` | *(pro)* | Submit via TPU | Low-latency live |
| `MultiPathSink` | *(pro)* | Jito + bloXroute + TPU | Max landing rate |

`BacktestSink` is the simplest — it writes each trade record to a Parquet file for later analysis. `PaperTradeSink` stores records in SQLite and updates a running P&L. `JitoBundleSink` constructs a real Jito bundle, attaches a tip, signs with your wallet keypair, and submits it to the Jito block engine endpoint.

---

## Layer 5: Monitor (Observability)

The Monitor is not a separate class but a cross-cutting concern implemented in `PipelineRunner`. Every transition between layers is logged via structlog with a structured event payload. Optional Prometheus metrics are exported when `monitoring.prometheus_port` is set in config.

### Tracked metrics

| Metric | Description |
|---|---|
| `detection_rate` | Opportunities detected per minute |
| `sim_success_rate` | Fraction of simulations returning `profitable=True` |
| `landing_rate` | Fraction of submitted bundles confirmed on-chain |
| `pnl_per_strategy` | Cumulative net P&L per strategy/detector |
| `pipeline_latency_ms` | Time from StateUpdate receipt to Sink submission |

---

## Mode Switching: Same Code, Different Adapters

The key design insight of mev-kit is that **the strategy (Detector) is completely decoupled from the execution environment**. A `CEXDEXArbDetector` does not know or care whether it is:

- Processing a Parquet replay of last Tuesday's data (backtest mode)
- Receiving live Helius + Binance data but not submitting real transactions (paper mode)
- Running with full Jito bundle submission (live mode)

The `PipelineRunner` is configured with concrete adapter instances, and the strategy only sees the abstract interface. Switching from backtest to paper to live is a config file change, not a code change.

```toml
# config/free.toml (backtest section)
[pipeline.backtest]
ingest = "ParquetReplayAdapter"
simulator = "RPCSimulator"
sink = "BacktestSink"

[pipeline.paper]
ingest = ["HeliusWSAdapter", "BinanceWSAdapter"]
simulator = "RPCSimulator"
sink = "PaperTradeSink"

[pipeline.live]
ingest = ["HeliusWSAdapter", "BinanceWSAdapter"]
simulator = "RPCSimulator"
sink = "JitoBundleSink"
```

---

## Data Flow in Detail

Here is the sequence of events for a single arbitrage opportunity, from detection to execution:

```
1. BinanceWSAdapter receives a SOL/USDC price tick from Binance
   → emits PriceUpdate into the async queue

2. PipelineRunner.run_loop() dequeues the PriceUpdate
   → calls detector.process(PriceUpdate)

3. CEXDEXArbDetector updates its internal cex_price state
   → no opportunity yet (waiting for pool state)

4. HeliusWSAdapter receives a Raydium pool account update
   → emits PoolState into the async queue

5. PipelineRunner dequeues the PoolState
   → calls detector.process(PoolState)

6. CEXDEXArbDetector calculates spread = 65 bps, net spread = 18 bps
   → net spread > min_spread_bps (15 bps threshold)
   → returns Opportunity(type=CEX_DEX_ARB_BUY, ...)

7. PipelineRunner receives non-None Opportunity
   → calls simulator.simulate(opportunity)

8. RPCSimulator constructs swap transaction
   → calls Helius simulateTransaction RPC
   → returns SimulationResult(profitable=True, net_profit_usd=0.09)

9. PipelineRunner receives profitable SimulationResult
   → calls sink.send(opportunity, simulation_result)

10. JitoBundleSink (or PaperTradeSink in paper mode):
    → constructs Jito bundle with swap transaction + tip
    → signs with wallet keypair
    → submits to Jito block engine
    → logs ExecutionResult to Monitor

11. Monitor logs all events with timestamps
    → updates pipeline latency histogram
    → increments detection_rate, landing_rate counters
```

Total wall-clock time for steps 1–10 in live mode: typically 200–600ms on a well-connected server.

---

## Further Reading

- [Guide 4: Writing a Custom Detector](./04-custom-detector.md)
- [Guide 5: Backtesting Your Strategy](./05-backtesting.md)
- Source: `src/mev_kit/pipeline/runner.py`
- Source: `src/mev_kit/adapters/`
- Source: `src/mev_kit/strategies/`
