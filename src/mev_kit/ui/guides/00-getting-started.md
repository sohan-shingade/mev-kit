# Getting Started with mev-kit

mev-kit is a Python framework for detecting, simulating, and backtesting MEV (Maximal Extractable Value) strategies on Solana. This guide takes you from a fresh install to a running backtest in under 10 minutes — no API keys required.

---

## Prerequisites

- **Python 3.11+** — check with `python --version`
- **A terminal** — bash, zsh, or PowerShell all work
- **A free Helius API key** — only needed for paper trading and live mode, not backtesting

No paid subscriptions, no blockchain node, no wallet required to get started.

---

## Installation

Install from PyPI:

```bash
pip install mev-kit
```

Or install from source for the latest development version:

```bash
git clone https://github.com/your-org/mev-kit
cd mev-kit
pip install -e ".[dev]"
```

Verify the install:

```bash
mev-kit --version
```

---

## Your First Backtest (No API Keys Needed)

Backtesting uses historical price data downloaded from Binance, which is free and requires no account. The full flow is: fetch data → launch the UI → run backtest → view results.

### Step 1: Download Historical Data

The easiest way is through the web UI. Go to the **Data** page, find the **Fetch Binance OHLCV** panel, select SOLUSDT as the symbol, set the interval to **1s**, and click **Fetch Binance Data**. The file saves automatically and appears in the file list above.

Alternatively, use the fetch script from the command line:

```bash
python scripts/fetch_binance_history.py \
  --symbol SOLUSDT \
  --interval 1s \
  --days 1 \
  --output ./data/
```

This writes a Parquet file to `./data/SOLUSDT_1s_1d.parquet`. Parquet is a compressed columnar format — 1 day of 1-second bars is typically around 5 MB.

### Step 2: Launch the Web UI

```bash
mev-kit ui
```

The UI opens at [http://localhost:8080](http://localhost:8080). Keep this terminal running — it hosts the backend.

### Step 3: Run a Backtest

1. Click the **Backtest** tab in the top navigation
2. Under **Data File**, select your downloaded Parquet file
3. Review the strategy parameters (defaults are reasonable for a first run)
4. Click **Run Backtest**

The backtest runs in-process and typically completes in a few seconds for a single day of data.

### Step 4: Analyze Results

When the backtest finishes, the Backtest page displays:

- **Summary cards** — total trades, P&L, win rate, average spread
- **Trade table** — every individual trade with direction, spread, and estimated profit

Click **Export CSV** to download the trade list. Click **Tweak & Re-run** to go back to the config form and adjust parameters.

For deeper analysis with charts (P&L curve, spread distribution, direction breakdown), open the **Analysis** page and select your results database.

---

## Setting Up API Keys (Paper Trading and Live Mode)

For backtesting, you don't need any keys. For paper trading against live on-chain data, you need a free Helius key. Live trading additionally requires a wallet keypair.

### HELIUS_API_KEY (free tier, required for paper trading)

1. Go to [https://helius.dev](https://helius.dev)
2. Sign up for a free account
3. Create a new project — name it anything
4. Copy the API key from the project dashboard

Set it in your shell:

```bash
export HELIUS_API_KEY=your-key-here
```

To persist across sessions, add that line to your `~/.zshrc` or `~/.bashrc`.

### HELIUS_RPC_URL (optional)

mev-kit auto-constructs this from your API key. You only need to set it if you want to use a custom endpoint:

```bash
export HELIUS_RPC_URL=https://mainnet.helius-rpc.com/?api-key=your-key
```

### WALLET_KEYPAIR_PATH (live mode only)

Required only when running `mev-kit live`. This should be a path to a Solana keypair JSON file, typically generated with the Solana CLI:

```bash
solana-keygen new --outfile ~/.config/solana/mev-wallet.json
export WALLET_KEYPAIR_PATH=/path/to/keypair.json
```

Never fund this wallet with more than you are prepared to lose. Start with the minimum needed to pay transaction fees.

### JITO_BLOCK_ENGINE_URL (live mode only)

Defaults to the Jito mainnet block engine. You almost never need to change this:

```bash
export JITO_BLOCK_ENGINE_URL=https://mainnet.block-engine.jito.wtf
```

### Checking Key Status in the UI

Open the **Config** page and scroll to the **API Keys** section. Each key shows as green (set) or red (missing). This is the fastest way to confirm your environment is wired up correctly before starting a live or paper run.

---

## Paper Trading Setup

Once `HELIUS_API_KEY` is set, paper trading runs against live on-chain data but executes no real transactions. It's the closest thing to live mode without risking funds.

1. Launch the UI:
   ```bash
   mev-kit ui
   ```

2. Go to the **Dashboard** tab

3. Set the mode dropdown to **Paper**, then click **Start**

4. The opportunity feed begins populating within seconds as the Helius WebSocket streams pool state updates

5. Adjust strategy parameters live using the **Hot Params** panel on the right — changes take effect on the next detection cycle without restarting

---

## Understanding the Key Config Parameters

Open the **Config** tab in the UI for a visual editor. Here are the parameters you'll tune most often:

| Parameter | What it controls | Where to start |
|-----------|-----------------|----------------|
| `min_spread_bps` | Minimum spread (in basis points) that triggers an opportunity signal. 1 bps = 0.01%. | 15–20 bps |
| `position_size_sol` | How much SOL to commit per trade. | 0.01 SOL |
| `fee_bps` | DEX swap fee. Raydium v4 is 30 bps; CLMM pools vary. | 30 |
| `circuit_breaker_enabled` | Auto-pauses the strategy after N consecutive losses. | true |
| `circuit_breaker_max_losses` | Number of consecutive losses before the circuit trips. | 3 |

A spread of 15 bps means the CEX price and DEX price differ by 0.15%. After accounting for a 30 bps swap fee on each leg, you need at least 60 bps of spread to be net positive — so `min_spread_bps` of 15 is conservative by design.

For the theory behind these numbers, read the **How CEX-DEX Arbitrage Works** guide.

---

## Common Pool Addresses

When configuring which pools to monitor, use these Raydium pool addresses:

| Pool | Address |
|------|---------|
| SOL/USDC (Raydium) | `58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2` |
| SOL/USDT (Raydium) | `7XawhbbxtsRcQA8KTkHT9f9nc6d69UwqCDh6U5EEbEmX` |
| mSOL/SOL (Raydium) | `EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U` |
| JitoSOL/SOL (Raydium) | `2uoKbPEidR7FBnCHsMPkjRsH4pMtDMgw7f8ickPRPfwK` |
| RAY/USDC (Raydium) | `6UmmUiYoBjSrhakAobJw8BvkmJtDVxaeBtbt7rxWo1mg` |

SOL/USDC is the highest-volume pool and the best starting point. It has the most CEX-DEX spread activity and the tightest on-chain liquidity.

You can enter pool addresses directly in the Config page or pass them via the `pool_addresses` config key in `config/free.toml`.

---

## Next Steps

Once you have a backtest running, here is a natural progression:

1. **Read "How CEX-DEX Arbitrage Works"** — understand why the spread exists, how latency affects profitability, and what the fee math looks like before you interpret backtest results

2. **Tune and re-run** — adjust `min_spread_bps` and `position_size_sol` in the Config page and re-run the backtest to see how the parameter changes affect P&L

3. **Fetch more data** — on the **Data** page, set Days to 7 or 30 and re-fetch to backtest over a longer window and reduce the effect of any single day's volatility

4. **Set up paper trading** — get a free Helius key, set `HELIUS_API_KEY`, and run the strategy against live data without spending anything

5. **Read "Writing a Custom Detector"** — build your own strategy on top of the same pipeline abstractions, whether that's liquidation hunting, sandwich detection, or something entirely new

6. **Check External Resources** — the guides link out to Solana documentation, Jito docs, and Helius API references when you need to go deeper on the infrastructure layer

---

## Troubleshooting

**`mev-kit: command not found`** — make sure the Python scripts directory is on your PATH. After `pip install mev-kit`, try `python -m mev_kit` as a fallback.

**`ModuleNotFoundError: No module named 'mev_kit'`** — you likely have multiple Python environments. Run `which python` and `which pip` to confirm they point to the same environment.

**`Connection refused` on http://localhost:8080** — the `mev-kit ui` process may have exited. Check the terminal where you launched it for error output.

**Backtest returns zero trades** — the default `min_spread_bps` may be too high for the data period you fetched. Try lowering it to 5 bps to confirm the pipeline is working, then raise it back to filter for realistic opportunities.

**Helius WebSocket disconnects** — free tier connections have rate limits. If you see repeated disconnects, check the Helius dashboard for quota usage. The adapter retries with exponential backoff automatically, so brief disconnections self-heal.
