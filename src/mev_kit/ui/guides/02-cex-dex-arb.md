# How CEX-DEX Arbitrage Works

## The Core Concept

CEX-DEX arbitrage exploits temporary price differences between a centralized exchange (CEX) and a decentralized exchange (DEX) for the same asset pair. In mev-kit's reference implementation, the pair is SOL/USDC, the CEX is Binance, and the DEX is Raydium.

The strategy is conceptually simple:

1. Receive a live price tick from Binance via WebSocket
2. Receive the current pool state from Raydium (via Helius or Geyser)
3. Calculate the spread between the two prices
4. If the spread exceeds a profitable threshold, submit a swap on Raydium

The difficulty lies not in the concept but in the execution: speed, fee management, simulation, and position sizing all determine whether a strategy is net profitable over time.

---

## Price Representations

Before covering the math, it helps to be precise about what "price" means in each venue.

### Binance Price

Binance streams best-bid and best-ask prices via WebSocket. The mid-price is `(best_bid + best_ask) / 2`. For most arb calculations, you use the side you intend to trade against:

- If you are **buying SOL on Binance** (to hedge a DEX sell), use the **ask price** (the price at which Binance will sell to you)
- If you are **selling SOL on Binance** (to hedge a DEX buy), use the **bid price** (the price at which Binance will buy from you)

For simplicity, mev-kit's `CEXDEXArbDetector` uses the mid-price as a signal and treats the bid-ask spread as part of execution cost.

### Raydium (DEX) Price

Raydium's constant-product AMM prices assets according to the formula `x * y = k`, where `x` and `y` are the reserve amounts of each token. The instantaneous price is:

```
price = reserve_quote / reserve_base
```

For SOL/USDC: `price = usdc_reserve / sol_reserve`

This is the price for an infinitesimally small trade. Any real trade larger than zero moves the price. Larger trades face worse effective prices — this is **price impact** (also called slippage in the AMM context).

The `PoolState` model in mev-kit carries `reserve_base`, `reserve_quote`, and a `fee_bps` field used in spread calculations.

---

## Spread Calculation

The raw spread between CEX and DEX prices, expressed in basis points (bps), is:

```
spread_bps = |cex_price - dex_price| / cex_price * 10000
```

One basis point equals 0.01%. A spread of 30bps means the two prices differ by 0.30%.

In Python:

```python
def calculate_spread_bps(cex_price: float, dex_price: float) -> float:
    """Calculate the absolute spread between CEX and DEX prices in basis points."""
    return abs(cex_price - dex_price) / cex_price * 10_000
```

This raw spread is gross — it does not account for fees. A spread of 30bps with 30bps in fees yields zero net profit.

---

## Net Spread After Fees

The net spread is the gross spread minus all fees paid to execute the trade:

```
net_spread_bps = spread_bps - fee_bps
```

Where `fee_bps` includes:

| Cost | Typical Value | Notes |
|---|---|---|
| Raydium swap fee | 25–30 bps | Charged on each swap |
| Priority fee | 1–10 bps | Depends on congestion |
| Jito tip | 1–20 bps | Depends on competition |
| Binance trading fee | 2–10 bps | Depends on tier |
| Slippage | variable | Depends on position size and pool depth |

For a basic calculation using Raydium at 30bps and a Jito tip of 10bps:

```python
RAYDIUM_FEE_BPS = 30
ESTIMATED_PRIORITY_AND_TIP_BPS = 10

def net_spread_bps(gross_spread_bps: float) -> float:
    total_fees = RAYDIUM_FEE_BPS + ESTIMATED_PRIORITY_AND_TIP_BPS
    return gross_spread_bps - total_fees
```

A strategy is viable only when `net_spread_bps > 0`. In practice, you want a buffer above zero — called `min_spread_bps` in mev-kit config — to account for fee estimation error and execution variance.

---

## Trade Direction

The direction of the arb trade determines which venue you buy on and which you sell on. There are two cases:

### Case 1: DEX Price < CEX Price (BUY_DEX)

The on-chain price is below the Binance price. SOL is "cheap" on Raydium relative to Binance.

Action: buy SOL on Raydium (swap USDC for SOL), sell SOL on Binance.

```python
if dex_price < cex_price:
    direction = OpportunityType.BUY_DEX
```

### Case 2: DEX Price > CEX Price (SELL_DEX)

The on-chain price is above the Binance price. SOL is "expensive" on Raydium.

Action: sell SOL on Raydium (swap SOL for USDC), buy SOL on Binance.

```python
if dex_price > cex_price:
    direction = OpportunityType.SELL_DEX
```

In mev-kit, these correspond to the `OpportunityType` enum values `CEX_DEX_ARB_BUY` and `CEX_DEX_ARB_SELL` in `src/mev_kit/models/opportunity.py`.

The CEX leg (buying or selling on Binance) is not automated in the free-tier implementation. The mev-kit pipeline handles the on-chain (DEX) leg and logs the required CEX action. Full hedging automation is a pro-tier feature.

---

## Profit Estimation

Given a net spread in basis points and a position size in USDC, the estimated gross profit is:

```
profit_usd = (net_spread_bps / 10000) * position_size_usd
```

For example: a 20bps net spread on a $1,000 position yields $2.00 gross profit per trade.

In Python (as used in `CEXDEXArbDetector`):

```python
def estimate_profit(
    net_spread_bps: float,
    position_size_usd: float,
) -> float:
    """Estimate gross USD profit for a given spread and position size."""
    return (net_spread_bps / 10_000) * position_size_usd
```

### Position Size and Pool Depth

The `position_size_usd` parameter must be chosen carefully relative to the pool's liquidity. A large position on a shallow pool causes significant slippage, which can wipe out the spread entirely or even result in a loss.

The effective price you receive for a swap of size `delta_x` on a constant-product AMM is:

```
effective_price = y / (x + delta_x)  * delta_x / delta_x
               = y * x / ((x + delta_x) * x)
               ... simplifies to ...
price_impact_bps = delta_x / (x + delta_x) * 10000
```

A rough rule: limit position size to 0.1–0.5% of the pool's total liquidity to keep slippage below 10bps.

mev-kit exposes `max_position_size_usd` and `max_price_impact_bps` as config parameters. The simulator cross-checks these against real pool reserves before allowing a trade to proceed.

---

## Complete Spread Analysis Example

```python
# Prices
cex_price = 180.50   # Binance SOL/USDC mid-price
dex_price = 180.00   # Raydium instantaneous price
position_size_usd = 500.0

# Gross spread
gross_spread_bps = abs(cex_price - dex_price) / cex_price * 10_000
# = 0.50 / 180.50 * 10000 = 27.7 bps

# Fees
raydium_fee_bps = 30
priority_fee_bps = 5
jito_tip_bps = 8
binance_fee_bps = 4
total_fee_bps = raydium_fee_bps + priority_fee_bps + jito_tip_bps + binance_fee_bps
# = 47 bps

# Net spread (negative! Not profitable)
net_spread_bps = gross_spread_bps - total_fee_bps
# = 27.7 - 47 = -19.3 bps  --> SKIP

# If instead cex_price = 181.50 (1.50 spread):
gross_spread_bps_2 = abs(181.50 - 180.00) / 181.50 * 10_000
# = 1.50 / 181.50 * 10000 = 82.6 bps

net_spread_bps_2 = 82.6 - 47
# = 35.6 bps  --> PROFITABLE

profit_usd = (35.6 / 10_000) * 500.0
# = $0.178 per trade
```

A $0.178 profit per trade sounds small, but at high frequency — multiple trades per minute during volatile markets — it compounds meaningfully.

---

## When Arb Works (and When It Does Not)

### Favorable Conditions

- **High volatility**: large, rapid CEX price moves create bigger gaps before AMM prices adjust
- **Shallow DEX liquidity**: a thinner pool amplifies price impact of any trade, making the stale price persist longer (though it also increases your own slippage)
- **High DEX volume**: counterintuitively, high volume means more organic trades rebalancing the pool, but also more frequent opportunities when volume is directional
- **Low congestion**: lower priority fee requirements mean the bar for profitability is lower

### Unfavorable Conditions

- **Low volatility / sideways markets**: CEX and DEX prices track each other closely, spreads are tiny
- **Very deep DEX liquidity**: large pools are harder to move, so the spread closes quickly after any price update; your advantage window is shorter
- **High network congestion**: priority fees spike, compressing or eliminating net spread
- **Many active competitors**: other searchers submit transactions in the same window, reducing your landing rate or forcing you to over-tip
- **Stale data**: if your price feeds have higher latency than competitors, by the time you see an opportunity it may already be gone

---

## Key Configuration Parameters

The `CEXDEXArbDetector` is configured via `config/free.toml` (or `pro.toml`). The relevant fields are:

```toml
[strategy.cex_dex_arb]
min_spread_bps = 50          # Minimum net spread to emit an Opportunity
position_size_usd = 100.0    # Trade size per opportunity
max_price_impact_bps = 20    # Reject if estimated slippage exceeds this
fee_bps = 30                 # DEX swap fee (Raydium)
```

Start with a generous `min_spread_bps` (e.g., 80–100) when backtesting to find the most obvious opportunities, then reduce it gradually as you tune your fee estimates and gain confidence in the simulation results.

---

## Further Reading

- [Guide 1: MEV on Solana](./01-mev-on-solana.md)
- [Guide 3: The mev-kit Pipeline](./03-pipeline.md)
- [Guide 5: Backtesting Your Strategy](./05-backtesting.md)
- Raydium AMM whitepaper (constant-product formula details)
- Binance WebSocket API docs (for price stream formats)
