# Backtesting Your Strategy

## Why Backtest?

Before committing real capital to a strategy, backtesting lets you answer the most important questions cheaply:

- Does this strategy generate net-positive P&L over historical data?
- What are the best parameter values (`min_spread_bps`, `position_size_usd`, etc.)?
- How sensitive is profitability to fee assumptions?
- How frequently does the strategy trigger, and what is the distribution of trade sizes?
- Does it work in all market conditions, or only during high volatility?

Backtesting in mev-kit replaces live data sources (`HeliusWSAdapter`, `BinanceWSAdapter`) with `ParquetReplayAdapter`, which reads local Parquet files of historical pool states and price ticks. The strategy, simulator, and result logging are identical to live mode.

---

## Step 1: Fetch Historical Data

You need two Parquet files:
1. Historical Raydium pool states (reserve snapshots at each transaction)
2. Historical Binance price ticks for SOL/USDC

### Option A: Fetch Raydium Pool States via Helius

```bash
python scripts/fetch_historical.py \
  --pool SOL/USDC \
  --days 7 \
  --output ./data/
```

This script calls the Helius transaction history API to reconstruct the reserve state of the SOL/USDC Raydium pool at each swap. Output is `./data/raydium_sol_usdc_7d.parquet`.

Required environment variable: `HELIUS_API_KEY`.

The free Helius tier rate-limits at 10 requests/second. For a 7-day backtest this typically takes 10–30 minutes depending on pool activity.

### Option B: Fetch Binance Historical Klines

```bash
python scripts/fetch_binance_history.py \
  --symbol SOLUSDC \
  --interval 1s \
  --days 7 \
  --output ./data/
```

This script calls the Binance REST API for 1-second kline (OHLCV) data, which is a reasonable approximation of the tick stream. Output is `./data/binance_solusdc_7d.parquet`. No API key required for public kline data.

### What the Parquet Files Contain

```
raydium_sol_usdc_7d.parquet
  ├── timestamp_ms     int64     Unix timestamp in milliseconds
  ├── pool_address     string    Raydium pool account address
  ├── reserve_base     float64   SOL reserves at this point in time
  ├── reserve_quote    float64   USDC reserves at this point in time
  ├── fee_bps          int32     Pool fee (30 for Raydium standard)
  └── slot             int64     Solana slot number

binance_solusdc_7d.parquet
  ├── timestamp_ms     int64     Kline open timestamp
  ├── symbol           string    "SOLUSDC"
  ├── open             float64
  ├── high             float64
  ├── low              float64
  ├── close            float64   Used as CEX price
  └── volume           float64
```

---

## Step 2: Configure Strategy Parameters

Edit `config/free.toml` (or create a copy for your experiment):

```toml
[pipeline.backtest]
ingest = "ParquetReplayAdapter"
simulator = "RPCSimulator"       # Uses simulateTransaction; set to "NoopSimulator" to skip
sink = "BacktestSink"

[ingest.parquet_replay]
pool_file = "./data/raydium_sol_usdc_7d.parquet"
price_file = "./data/binance_solusdc_7d.parquet"
speed_multiplier = 0             # 0 = as fast as possible; 1 = real-time; 10 = 10x

[strategy]
class = "mev_kit.strategies.cex_dex_arb.CEXDEXArbDetector"

[strategy.params]
pool_address = "8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ"
cex_symbol = "SOLUSDC"
min_spread_bps = 50.0            # Start wide; reduce gradually
position_size_usd = 100.0        # Keep small during initial testing
fee_bps = 30                     # Raydium pool fee
cooldown_ms = 1000               # Prevent re-entry within 1 second

[backtest]
output_file = "./results/backtest_run_001.parquet"
```

### Key parameters and their trade-offs

| Parameter | Effect of lowering | Effect of raising |
|---|---|---|
| `min_spread_bps` | More trades, more total P&L, higher false-positive rate | Fewer trades, higher confidence per trade |
| `position_size_usd` | Lower absolute P&L, lower slippage | Higher absolute P&L, higher slippage risk |
| `cooldown_ms` | More trades per price spike | Fewer duplicate entries |
| `fee_bps` | Optimistic about costs | Pessimistic (conservative) |

Start with `min_spread_bps = 80–100` for your first run. This catches only the most obvious opportunities and gives you a realistic ceiling on what is achievable. Once the strategy is behaving correctly, reduce the threshold gradually.

---

## Step 3: Run the Backtest

### Via CLI

```bash
mev-kit backtest \
  --config config/free.toml \
  --strategy cex-dex-arb \
  --data ./data/raydium_sol_usdc_7d.parquet
```

The `--data` flag overrides the `pool_file` in config for convenience. Add `--price-data` to also override the price file:

```bash
mev-kit backtest \
  --config config/free.toml \
  --strategy cex-dex-arb \
  --data ./data/raydium_sol_usdc_7d.parquet \
  --price-data ./data/binance_solusdc_7d.parquet \
  --output ./results/run_001.parquet
```

While the backtest runs, the CLI prints a live summary:

```
[00:00:12] Replaying: 2024-03-25 00:00:00 → 2024-03-26 00:00:00
[00:00:12] Updates processed: 14,822   Opportunities detected: 47
[00:00:12] Sim pass rate: 89.4%        Estimated P&L: $+3.21
[00:00:13] Replaying: 2024-03-26 00:00:00 → 2024-03-27 00:00:00
...
[00:01:08] Backtest complete. 7 days replayed in 68 seconds.
[00:01:08] Results written to ./results/run_001.parquet
```

### Via Python Script

```python
# examples/backtest_arb.py
import asyncio
from mev_kit.pipeline.runner import PipelineRunner
from mev_kit.strategies.cex_dex_arb import CEXDEXArbDetector
from mev_kit.adapters.ingest.parquet_replay import ParquetReplayAdapter
from mev_kit.adapters.simulators.rpc_simulator import RPCSimulator
from mev_kit.adapters.sinks.backtest import BacktestSink

async def main() -> None:
    detector = CEXDEXArbDetector(
        pool_address="8HoQnePLqPj4M7PUDzfw8e3Ymdwgc7NaYyHCrP3L7XUZ",
        cex_symbol="SOLUSDC",
        min_spread_bps=50.0,
        position_size_usd=100.0,
    )

    runner = PipelineRunner(
        ingest_adapters=[
            ParquetReplayAdapter(
                pool_file="./data/raydium_sol_usdc_7d.parquet",
                price_file="./data/binance_solusdc_7d.parquet",
                speed_multiplier=0,  # run as fast as possible
            )
        ],
        detector=detector,
        simulator=RPCSimulator(),
        sink=BacktestSink(output_path="./results/run_001.parquet"),
    )

    await runner.run()

asyncio.run(main())
```

### Via Web UI

Navigate to the **Backtest** tab in the mev-kit web UI:

1. Select or upload your Parquet data files
2. Choose a strategy (`cex-dex-arb` or a custom detector)
3. Set strategy parameters in the form
4. Click **Run Backtest**
5. The results appear in the **Analysis** tab when complete

---

## Step 4: Analyze Results

The `BacktestSink` writes a Parquet file with one row per opportunity that passed simulation. Each row is a `PaperTradeRecord`.

### Using the Analysis Script

```bash
python scripts/analyze_results.py \
  --input ./results/run_001.parquet \
  --report text
```

Output:

```
=== Backtest Summary ===
Period:               2024-03-25 → 2024-04-01 (7 days)
Total opportunities:  312
Simulated profitable: 279 (89.4%)
Opportunities taken:  279

P&L Summary
-----------
Total estimated P&L:  $+14.73
Average per trade:    $+0.053
Best trade:           $+0.82
Worst trade:          $-0.11  (simulation error corrected post-hoc)
Sharpe (daily):       1.42

Trade Distribution
------------------
By direction:         BUY_DEX  58.4%  |  SELL_DEX  41.6%
By net spread (bps):  p25=18  p50=32  p75=61  p95=124
By hour of day:       peak hours 13:00–17:00 UTC

Spread Breakdown
----------------
Mean gross spread:    64.2 bps
Mean total fees:      44.0 bps
Mean net spread:      20.2 bps
```

### Using the Web UI Analysis Page

The **Analysis** page in the mev-kit web UI renders the same data interactively:

- P&L curve over time (cumulative and per-trade)
- Spread distribution histogram
- Heatmap of opportunity frequency by hour and day of week
- Parameter sensitivity sweep (vary `min_spread_bps` and see projected P&L)

### Using Polars Directly

The result file is a standard Parquet file — you can query it with Polars or pandas:

```python
import polars as pl

df = pl.read_parquet("./results/run_001.parquet")
print(df.schema)

# Total P&L
total_pnl = df["estimated_profit_usd"].sum()
print(f"Total P&L: ${total_pnl:.2f}")

# Trades per day
df.with_columns(
    pl.from_epoch("detected_at_ms", time_unit="ms").dt.date().alias("date")
).group_by("date").agg(
    pl.len().alias("trades"),
    pl.sum("estimated_profit_usd").alias("daily_pnl"),
).sort("date").head(10)
```

---

## Step 5: Iterate

Backtesting is valuable only through iteration. A single run tells you little. The workflow is:

1. Run with wide parameters (high `min_spread_bps`) — establish the ceiling
2. Tighten parameters one at a time — find the profitability frontier
3. Test on a different time period — check robustness
4. Compare against different strategies — rank by Sharpe, not just P&L

### Iteration Example

```bash
# Run 1: wide threshold, large position
mev-kit backtest --config config/run1.toml --output results/run1.parquet
# → P&L: $+14.73 over 7 days, 279 trades

# Run 2: tighter threshold
# Edit: min_spread_bps = 30
mev-kit backtest --config config/run2.toml --output results/run2.parquet
# → P&L: $+19.40 over 7 days, 512 trades (more trades, thinner each)

# Run 3: tighter still
# Edit: min_spread_bps = 15
mev-kit backtest --config config/run3.toml --output results/run3.parquet
# → P&L: $+11.20 over 7 days, 1,241 trades (marginal trades drag down average)

# Compare runs
python scripts/analyze_results.py \
  --input results/run1.parquet results/run2.parquet results/run3.parquet \
  --compare
```

The sweet spot is typically where `net_spread_bps` distribution shows most trades well above zero, not squeezed against the threshold.

---

## Tips and Warnings

### Start Wide, Reduce Gradually

If you start with `min_spread_bps = 5` and your total fees are 45bps, almost every trade will be unprofitable. Start at 80–100bps and reduce until you find the edge of profitability. The goal is to understand the shape of the distribution before optimizing.

### Watch Out for Overfitting

If you tune `min_spread_bps` to the exact value that maximizes P&L on your 7-day dataset, that value is almost certainly overfit to the specific market conditions of those 7 days. To test robustness:

- Hold out the last 2 days of data and do not touch it until your final evaluation
- Run backtests on multiple separate weeks
- Check if the optimal threshold is consistent across periods

A strategy that works only on the data it was tuned against is not a strategy — it is a historical fit.

### Fee Assumptions Matter

The biggest source of error in backtesting is fee estimation. Common mistakes:

- **Forgetting Binance trading fees** (2–10bps depending on your tier)
- **Using the average Jito tip** when in practice you need to pay the competition-clearing tip, which is higher during high-volatility periods
- **Ignoring slippage** for larger position sizes

It is better to overestimate fees in backtesting and be pleasantly surprised in live trading than the reverse. A common convention is to add a 20% buffer on top of your estimated fee total:

```toml
[strategy.params]
# Actual fees: 30 (Raydium) + 8 (tip) + 4 (Binance) + 5 (priority) = 47 bps
# With 20% buffer: 47 * 1.2 = 56.4 bps → round to 60
fee_bps = 60
```

### Simulation Latency in Backtesting

`RPCSimulator` calls Helius `simulateTransaction` for each opportunity, which adds real latency to your backtest. For large datasets, this can make a backtest take hours.

To speed up backtests, use `NoopSimulator` (which passes everything through) for parameter sweeps, then re-run with `RPCSimulator` only for your final candidate configuration.

```toml
[pipeline.backtest]
simulator = "NoopSimulator"   # Fast, no RPC calls; use for parameter sweeps
# simulator = "RPCSimulator"  # Accurate, slow; use for final validation
```

### Landing Rate Is Not Modeled in Backtesting

The backtest assumes every opportunity that passes simulation would have been executed successfully. In live trading, the landing rate (fraction of submitted bundles that actually land on-chain) is typically 60–95% depending on competition and tip sizing.

When extrapolating backtest P&L to expected live P&L, multiply by your expected landing rate. If landing rate is 80%, your expected live P&L is approximately 80% of the backtest figure.

---

## Checklist Before Going Live

Use this checklist after backtesting and before running in paper or live mode:

- [ ] Backtest covers at least 14 days of varied market conditions
- [ ] Results hold on a held-out validation period not used for tuning
- [ ] Fee assumptions include Raydium fee, Binance fee, priority fee, and Jito tip
- [ ] `min_spread_bps` is comfortably above your total fee estimate
- [ ] Position size is less than 0.5% of pool liquidity (to limit slippage)
- [ ] Strategy has been tested with `PaperTradeSink` for at least 24 hours
- [ ] `WALLET_KEYPAIR_PATH` and `JITO_BLOCK_ENGINE_URL` are configured
- [ ] Wallet holds sufficient SOL for fees and position sizing

---

## Further Reading

- [Guide 2: How CEX-DEX Arbitrage Works](./02-cex-dex-arb.md)
- [Guide 3: The mev-kit Pipeline](./03-pipeline.md)
- [Guide 4: Writing a Custom Detector](./04-custom-detector.md)
- Source: `scripts/fetch_historical.py`
- Source: `scripts/analyze_results.py`
- Source: `src/mev_kit/adapters/ingest/parquet_replay.py`
- Source: `src/mev_kit/adapters/sinks/backtest.py`
