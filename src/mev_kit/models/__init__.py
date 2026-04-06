"""Core data models for mev-kit pipeline.

These Pydantic models define the typed contracts between pipeline layers.
Every piece of data flowing through the pipeline is one of these types.
No raw dicts. No untyped data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ============================================================
# Enums
# ============================================================


class Source(StrEnum):
    """Where a state update originated."""

    HELIUS_WS = "helius_ws"
    YELLOWSTONE_GRPC = "yellowstone_grpc"
    GEYSER = "geyser"
    BINANCE_WS = "binance_ws"
    JUPITER_API = "jupiter_api"
    PARQUET_REPLAY = "parquet_replay"
    PUBLIC_RPC = "public_rpc"


class OpportunityType(StrEnum):
    """Classification of MEV opportunity."""

    CEX_DEX_ARB = "cex_dex_arb"
    ATOMIC_ARB = "atomic_arb"
    LIQUIDATION = "liquidation"
    BACKRUN = "backrun"
    JIT_LIQUIDITY = "jit_liquidity"
    STATISTICAL_ARB = "statistical_arb"


class Direction(StrEnum):
    """Trade direction for the MEV capture."""

    BUY_DEX = "buy_dex"
    SELL_DEX = "sell_dex"
    BUY = "buy"
    SELL = "sell"


class ExecutionMode(StrEnum):
    """Pipeline execution mode."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


# ============================================================
# State Updates (Layer 1 → Layer 2)
# ============================================================


class PoolState(BaseModel):
    """State of a DEX liquidity pool at a point in time."""

    pool_address: str
    dex: str  # "raydium", "orca", "phoenix"
    base_mint: str
    quote_mint: str
    base_reserve: float
    quote_reserve: float
    price: float  # quote_reserve / base_reserve
    fee_bps: int = 30  # default 0.3%
    slot: int
    timestamp: datetime


class PriceUpdate(BaseModel):
    """Price update from any source (CEX or DEX)."""

    symbol: str  # "SOL/USDC", "SOL/USDT"
    price: float
    volume: float | None = None
    source: Source
    timestamp: datetime
    slot: int | None = None  # only for on-chain sources


class StateUpdate(BaseModel):
    """Universal state update — the input type for all detectors.

    A StateUpdate wraps either a PoolState or a PriceUpdate (or both)
    and carries metadata about its origin. Detectors consume these
    and decide whether an opportunity exists.
    """

    source: Source
    pool: PoolState | None = None
    price: PriceUpdate | None = None
    raw: dict[str, Any] | None = Field(default=None, exclude=True)
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================================================
# Opportunities (Layer 2 → Layer 3)
# ============================================================


class Opportunity(BaseModel):
    """A detected MEV opportunity, ready for simulation.

    Emitted by Detectors. Consumed by Simulators.
    Contains everything needed to construct and simulate the trade.
    """

    id: str = Field(description="Unique opportunity ID (uuid4)")
    type: OpportunityType
    direction: Direction
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Pricing
    dex_price: float
    reference_price: float  # CEX price or other-DEX price
    spread_bps: float
    estimated_profit_sol: float

    # Context
    pool_address: str
    dex: str
    pair: str  # "SOL/USDC"
    slot: int | None = None

    # For trade construction
    input_mint: str = ""
    output_mint: str = ""
    amount_in_lamports: int = 0

    # Metadata
    detector_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Simulation Results (Layer 3 → Layer 4)
# ============================================================


class SimulationResult(BaseModel):
    """Result of pre-execution simulation.

    Produced by Simulators. Consumed by Sinks (only if profitable).
    """

    opportunity_id: str
    profitable: bool
    net_profit_sol: float = 0.0
    net_profit_usd: float = 0.0
    gross_profit_sol: float = 0.0

    # Costs
    tip_lamports: int = 0
    priority_fee_lamports: int = 0
    compute_units: int = 0

    # Simulation metadata
    simulated: bool = True  # False if simulation was skipped
    sim_error: str | None = None
    sim_latency_ms: float = 0.0


# ============================================================
# Execution Results (Layer 4 output)
# ============================================================


class ExecutionResult(BaseModel):
    """Result of executing (or paper-trading) an opportunity."""

    opportunity_id: str
    mode: ExecutionMode
    success: bool

    # Live execution fields
    signature: str | None = None
    slot_landed: int | None = None
    bundle_id: str | None = None

    # Realized P&L
    realized_profit_sol: float = 0.0
    realized_profit_usd: float = 0.0
    tip_paid_lamports: int = 0

    # Timing
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    latency_ms: float = 0.0

    # Paper trade fields
    theoretical_profit_sol: float = 0.0

    error: str | None = None


# ============================================================
# Pipeline Config
# ============================================================


class PipelineConfig(BaseModel):
    """Top-level pipeline configuration loaded from TOML."""

    mode: ExecutionMode = ExecutionMode.PAPER
    strategy: str = "cex_dex_arb"

    # Ingest
    ingest_adapters: list[str] = Field(default_factory=lambda: ["helius_ws", "binance_ws"])

    # Strategy params
    min_spread_bps: float = 15.0
    position_size_sol: float = 0.01
    max_position_size_sol: float = 1.0

    # Simulation
    simulator: str = "rpc"
    simulate_before_execute: bool = True

    # Execution
    sink: str = "paper_trade"
    tip_percentage: float = 0.4  # 40% of expected profit
    min_tip_lamports: int = 10_000
    max_tip_lamports: int = 1_000_000

    # Risk
    max_daily_loss_sol: float = 0.1
    max_consecutive_misses: int = 5
    circuit_breaker_enabled: bool = True

    # Data
    results_db: str = "./data/results.db"
    parquet_dir: str = "./data/"

    # API keys (loaded from env)
    helius_api_key: str = ""
    helius_rpc_url: str = ""
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    jito_block_engine_url: str = "https://mainnet.block-engine.jito.wtf"
