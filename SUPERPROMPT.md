# MEV-KIT SUPERPROMPT
# Copy this entire file and paste it as your first message in Claude Code
# after opening the mev-kit project directory.

"""
You are building mev-kit, a Solana MEV research/development/deployment framework.
Read CLAUDE.md first — it's the complete project spec.

The project scaffold is already created with:
- All Pydantic models defined (src/mev_kit/models/__init__.py)
- All abstract base classes defined (IngestAdapter, Detector, Simulator, Sink)
- Pipeline runner implemented (src/mev_kit/pipeline/runner.py)
- Reference CEX-DEX arb detector implemented (src/mev_kit/strategies/cex_dex_arb.py)
- Paper trade + backtest sinks implemented (src/mev_kit/adapters/sinks/paper_trade.py)
- Parquet replay adapter implemented (src/mev_kit/adapters/ingest/parquet_replay.py)
- CLI scaffolded (src/mev_kit/cli.py)
- Core unit tests written (tests/unit/test_core.py)
- Config files for free and pro tiers (config/free.toml, config/pro.toml)

Here is the implementation plan. Execute each phase completely before moving
to the next. Run tests after each phase. Do not skip ahead.

## PHASE 1: Foundation — make the scaffold actually run

1. Install the project: `pip install -e ".[dev]"`
2. Run existing tests: `pytest tests/ -v` — fix any import errors
3. Verify CLI works: `mev-kit --help`
4. Fix any issues in the existing code until all tests pass and CLI responds

## PHASE 2: Helius WebSocket adapter (free tier, enables paper trading)

Create `src/mev_kit/adapters/ingest/helius_ws.py`:

- Implements IngestAdapter ABC
- Connects to Helius WebSocket endpoint for account subscriptions
- Subscribes to Raydium SOL/USDC AMM pool account changes
- Parses raw account data into PoolState objects
- Handles reconnection with exponential backoff (1s, 2s, 4s, max 30s)
- Config keys: helius_api_key, helius_ws_url, pool_addresses (list), commitment ("processed")
- Uses the `websockets` library
- The Raydium AMM pool address for SOL/USDC is: 58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2
- For MVP, use accountSubscribe RPC method over WebSocket
- Parse the pool reserves from the account data (Raydium AMM layout: base_reserve at offset 64, quote_reserve at offset 72, both u64 little-endian)
- Emit StateUpdate with source=Source.HELIUS_WS

Write tests in tests/unit/test_helius_ws.py:
- Test that adapter creates correct WebSocket subscription message
- Test that raw account data is parsed into valid PoolState
- Test reconnection logic (mock the websocket to simulate disconnect)

## PHASE 3: Binance WebSocket adapter (free, no API key needed)

Create `src/mev_kit/adapters/ingest/binance_ws.py`:

- Implements IngestAdapter ABC
- Connects to wss://stream.binance.com:9443/ws/solusdt@trade
- Parses trade messages into PriceUpdate objects
- Fields from Binance: p (price), q (quantity), T (timestamp ms)
- Handles reconnection with backoff
- Config keys: symbol (default "solusdt"), ws_url
- Emit StateUpdate with source=Source.BINANCE_WS

Write tests in tests/unit/test_binance_ws.py:
- Test parsing of a real Binance trade message format:
  {"e":"trade","E":1234567890,"s":"SOLUSDT","t":123,"p":"148.50","q":"10.5","T":1234567890123}
- Test that PriceUpdate has correct fields

## PHASE 4: RPC Simulator (free tier simulation)

Create `src/mev_kit/adapters/simulators/rpc_simulator.py`:

- Implements Simulator ABC
- Builds a swap transaction for the detected opportunity
- Calls simulateTransaction RPC method via httpx
- Parses simulation response: success/failure, compute units consumed, logs
- Computes net profit: output_amount - input_amount - priority_fee - tip
- Config keys: rpc_url (defaults to HELIUS_RPC_URL env var)
- For MVP, simulate a simple SOL→USDC swap via Raydium
- If simulation fails or is unprofitable, return SimulationResult(profitable=False)
- Track simulation latency in SimulationResult.sim_latency_ms

Write tests in tests/unit/test_rpc_simulator.py:
- Test with a mock RPC response (successful simulation)
- Test with a mock RPC response (failed simulation)
- Test profit calculation logic

## PHASE 5: Wire the full paper-trade pipeline

Update `src/mev_kit/cli.py` _run_paper function:

- Load config from TOML
- Read HELIUS_API_KEY and HELIUS_RPC_URL from environment variables
- Instantiate HeliusWSAdapter + BinanceWSAdapter
- Instantiate CEXDEXArbDetector with config params
- Instantiate RPCSimulator
- Instantiate PaperTradeSink
- Create Pipeline and run
- Handle Ctrl+C gracefully (call pipeline.stop())
- Print summary on exit

Write an integration test in tests/integration/test_paper_pipeline.py:
- Use ParquetReplayAdapter with synthetic test data instead of live feeds
- Verify the full pipeline: ingest → detect → simulate → sink
- Assert that opportunities are written to SQLite

## PHASE 6: Data fetching script

Create `scripts/fetch_historical.py`:

- Uses Helius RPC (httpx) to fetch historical Raydium pool states
- Method: call getMultipleAccounts for pool address at regular intervals
- Stores results as Parquet file with columns: pool_address, dex, base_mint, quote_mint, base_reserve, quote_reserve, price, fee_bps, slot, timestamp
- CLI args: --pool (address), --interval (seconds, default 5), --duration (minutes, default 60), --output (path)
- Requires HELIUS_API_KEY env var
- Prints progress: "Fetched slot 284729103 — price: 148.23 SOL/USDC"

Also create `scripts/fetch_binance_history.py`:
- Downloads historical Binance klines (candles) via REST API
- Endpoint: GET https://api.binance.com/api/v3/klines?symbol=SOLUSDT&interval=1s&limit=1000
- Stores as Parquet with columns: symbol, price (close), volume, timestamp
- CLI args: --symbol, --interval, --days, --output

## PHASE 7: Jito Bundle Sink (enables live mode)

Create `src/mev_kit/adapters/sinks/jito_bundle.py`:

- Implements Sink ABC
- Constructs a Jito bundle from the opportunity:
  1. Build swap transaction (Raydium AMM swap instruction)
  2. Build tip transaction (transfer SOL to Jito tip account)
  3. Wrap in Bundle (max 5 txs, atomic execution)
- Submits bundle to Jito block engine via HTTP POST
- Jito block engine URL: https://mainnet.block-engine.jito.wtf/api/v1/bundles
- Tip accounts (use any one): HFqU5x63VTqvQss8hp11i4bPuSPGQzLJXnjg2vavp1iU
- Config keys: jito_url, tip_percentage (default 0.4), min_tip_lamports, max_tip_lamports, keypair_path
- Loads wallet keypair from file for signing
- Returns ExecutionResult with bundle_id and signature if landed
- IMPORTANT: Add a dry_run config option that constructs the bundle but doesn't submit — logs what would have been sent

Write tests in tests/unit/test_jito_bundle.py:
- Test bundle construction (correct number of txs, tip amount)
- Test tip calculation (40% of expected profit, clamped to min/max)
- Test dry_run mode (no HTTP call made)

## PHASE 8: Monitoring and analysis

Create `src/mev_kit/utils/monitor.py`:

- Prometheus metrics using prometheus_client (optional dependency):
  - mev_kit_updates_total (counter)
  - mev_kit_opportunities_detected_total (counter, labels: type, detector)
  - mev_kit_simulation_duration_seconds (histogram)
  - mev_kit_execution_total (counter, labels: mode, success)
  - mev_kit_profit_sol_total (counter)
  - mev_kit_landing_rate (gauge)
- If prometheus_client not installed, silently no-op (don't crash)
- Expose metrics on HTTP port 9090 if enabled in config

Update `scripts/analyze_results.py`:
- Read SQLite results database
- Print summary table: total trades, win rate, total P&L, avg spread, best/worst trade
- Group by hour of day — when are opportunities most frequent?
- Group by spread bucket — what's the distribution?
- Optionally export to CSV

## PHASE 9: Testing and polish

- Run `ruff check src/ tests/` and fix all lint errors
- Run `mypy src/mev_kit/` and fix type errors
- Ensure test coverage > 80% on core modules (models, detector, pipeline, sinks)
- Add docstrings to any public method missing them
- Update README.md with actual usage examples that work
- Create `examples/backtest_arb.py` — a minimal 20-line script showing the full backtest flow
- Create `examples/paper_trade.py` — a minimal script showing paper trading setup
- Verify: `pip install -e .` works clean, `mev-kit --help` works, `pytest` passes

## IMPORTANT NOTES

- Always use async/await for I/O. Never use threads for network calls.
- All models are Pydantic v2. Use model_validate() not parse_obj().
- Use structlog for all logging, never print().
- WebSocket adapters MUST handle reconnection. The connection WILL drop.
- Never hardcode API keys. Always read from env vars or config.
- The free tier must work with $0 spend. No paid API calls in default config.
- Test with mocked external services. Never call real APIs in unit tests.
- Keep the adapter interface stable. Adding a new adapter should require
  zero changes to pipeline, detector, or sink code.

Run `cat CLAUDE.md` first, then begin with Phase 1.
"""
