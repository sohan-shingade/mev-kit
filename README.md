# mev-kit

Solana MEV research, development, and deployment framework.

Detect, simulate, backtest, and execute MEV strategies on Solana using a unified pipeline abstraction over fragmented external services. Same strategy code runs in backtest, paper-trade, and live-execution modes by swapping adapter implementations.

## Quick start

```bash
pip install -e ".[dev]"

# Backtest a strategy against historical data
mev-kit backtest --config config/free.toml --data ./data/raydium_sol_usdc.parquet

# Paper trade against live feeds (free, $0)
mev-kit paper --config config/free.toml

# Live execution with micro-positions
mev-kit live --config config/free.toml --size 0.01

# Analyze results
mev-kit analyze --db ./data/results.db
```

## Architecture

```
IngestAdapter → Detector → Simulator → Sink → Monitor
(data in)      (detect)    (validate)  (act)   (observe)
```

Every layer is a pluggable interface. Free-tier defaults ship with the package. Pro-tier implementations swap in via config.

## Free tier ($0/month)

| Layer | Implementation | Service |
|-------|---------------|---------|
| Ingest | HeliusWSAdapter | Helius free tier (30 RPS) |
| Ingest | BinanceWSAdapter | Binance public WebSocket |
| Ingest | ParquetReplayAdapter | Local files |
| Detect | CEXDEXArbDetector | Your CPU |
| Simulate | RPCSimulator | simulateTransaction via Helius |
| Sink | PaperTradeSink | SQLite |
| Sink | BacktestSink | Polars/Parquet |

## Pro tier ($15-50K/month)

| Layer | Implementation | Service |
|-------|---------------|---------|
| Ingest | GeyserAdapter | Own validator node |
| Ingest | YellowstoneGRPCAdapter | Triton/RPC Fast dedicated |
| Ingest | ShredStreamAdapter | Jito ShredStream |
| Simulate | ForkedValidatorSimulator | Local mainnet fork |
| Sink | JitoBundleSink | Jito block engine |
| Sink | MultiPathSink | Jito + bloXroute + TPU |

Same strategy code. Different adapters. Config change, not rewrite.

## License

MIT
