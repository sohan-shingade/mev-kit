# MEV on Solana: Concepts

## What is MEV?

Maximal Extractable Value (MEV) refers to profit that can be extracted from the process of including, excluding, or reordering transactions within a block. Originally coined as "Miner Extractable Value" in the Ethereum context, the term was broadened to "Maximal" as proof-of-stake chains and other architectures entered the picture.

In practice, MEV arises whenever a transaction's outcome depends on the order in which it is included relative to other transactions. A searcher — an entity running automated strategies — monitors the network for these opportunities and races to capture them before other searchers do.

Common MEV strategies include:
- **Arbitrage**: exploiting price differences between venues
- **Liquidations**: triggering undercollateralized loan repayments for a liquidation bonus
- **Sandwich attacks**: frontrunning and backrunning large swaps to profit from the induced price impact
- **JIT (Just-in-Time) liquidity**: providing concentrated liquidity just before a large swap and removing it immediately after

mev-kit focuses primarily on the first two categories, particularly CEX-DEX arbitrage.

---

## How Solana Differs from Ethereum for MEV

Understanding Solana's architecture is essential before writing any MEV strategy. Many assumptions that hold on Ethereum do not apply here.

### No Public Mempool

On Ethereum, submitted transactions sit in a publicly visible mempool before being included in a block. This mempool is the primary data source for MEV searchers — they watch incoming transactions and react to them.

Solana has no equivalent public mempool. Transactions are forwarded directly to the current slot leader (the validator whose turn it is to produce a block). There is no global gossip layer broadcasting pending transactions to everyone.

The practical consequence: **Solana MEV is not about watching pending transactions — it is about predicting what state will be profitable after the next state update arrives.**

### Continuous Block Production and ~400ms Slots

Ethereum produces a block roughly every 12 seconds. Solana produces one every ~400 milliseconds. That is approximately 30× faster.

Each slot is assigned to a specific validator according to a publicly known **leader schedule** that is published two epochs in advance (each epoch is ~2 days). Knowing the upcoming leader lets searchers optimize which block engine endpoint to use or whether to route through Jito.

The 400ms slot time compresses the window in which a price discrepancy can exist and be captured. Strategies need to react in tens of milliseconds, not seconds.

### Parallel Transaction Execution (Sealevel)

Solana's runtime, Sealevel, executes transactions in parallel when they touch different accounts. This increases throughput but also means that two arbitrage transactions touching the same pool accounts will serialize — only one can succeed. Failed transactions on Solana do not cost fees unless they fail inside the program (in which case they consume compute units and pay fees). A transaction that fails at preflight costs nothing.

This asymmetry (failed attempts are cheap) encourages high-volume spam from searchers, which is part of why Jito bundles became important.

### Transaction Fees and Priority Fees

Solana transactions pay a base fee plus an optional **priority fee** (called a compute unit price). Higher priority fees push a transaction ahead in the leader's local queue. During congestion, priority fees spike and can materially affect strategy profitability.

---

## Jito's Role

[Jito](https://jito.wtf) is the dominant MEV infrastructure layer on Solana. It operates a **block engine** — a service that accepts transaction bundles from searchers and forwards them to Jito-client validators.

### What is a Bundle?

A bundle is an atomic group of 1–5 transactions that must be included together, in order, or not at all. Atomicity means either all transactions land or none do. This is critical for strategies that require two legs (e.g., buy on DEX, hedge on CEX) to either both execute or both fail.

### The Tip Mechanism

Searchers attach a **tip** to their bundle — a SOL transfer to a Jito tip account. The tip is separate from priority fees and goes directly to the validator (shared between the validator and Jito). A higher tip increases the probability that the block engine prioritizes your bundle.

Tip sizing is a strategy parameter. Too low: your bundle loses to competitors. Too high: the tip exceeds the profit and the trade is unprofitable.

The `JitoBundleSink` in mev-kit handles tip calculation and bundle submission. It reads `min_tip_lamports` and `max_tip_lamports` from your config and interpolates based on estimated profit.

### Why Searchers Use Jito

1. **Atomicity**: multi-leg strategies execute safely without partial fills
2. **Priority**: bundles get favorable placement in the block
3. **Landing rate**: Jito validators represent a significant fraction of stake, increasing the probability your transactions land

---

## Types of MEV on Solana

### CEX-DEX Arbitrage

The most common and well-understood form. A centralized exchange (e.g., Binance) and a decentralized exchange (e.g., Raydium, Orca) both list the same asset. When the CEX price moves faster than the on-chain price updates, a brief window exists where you can buy cheap on one venue and sell on the other.

This is the primary strategy mev-kit ships with. See [Guide 2: How CEX-DEX Arbitrage Works](./02-cex-dex-arb.md) for details.

### Liquidations

Protocols like Marginfi, Mango, and Kamino allow users to borrow against collateral. If a borrower's collateral value drops below the required ratio, their position becomes liquidatable. Searchers monitor account states and submit liquidation transactions when a position crosses the threshold, collecting a liquidation bonus (typically 5–10% of the position).

Liquidations are more complex than arb because they require:
- Polling or subscribing to account state changes for all open positions
- Computing health ratios in real time
- Submitting the liquidation before competitors

### Backrunning

When a large swap moves the price of a pool significantly, there is often a reversion opportunity. A backrun transaction is submitted immediately after the large swap to capture the price correction. Unlike a sandwich attack, a backrun does not frontrun anything — it only reacts after the triggering transaction has landed.

Backrunning is generally considered less harmful to users than sandwich attacks.

### JIT (Just-in-Time) Liquidity

Liquidity providers on AMMs like Orca (Whirlpools) can observe incoming large swaps and add concentrated liquidity in the exact price range of the swap, collecting the swap fee, then removing liquidity in the same block. This requires very low latency and precise timing. It is more of an LP optimization strategy than a pure MEV strategy, but it competes with passive LPs for fee income.

---

## Why SOL/USDC Arb Exists

The SOL/USDC pair is the most liquid market on both Solana DEXs and Binance. It is also the canonical example for understanding CEX-DEX arb.

Here is why the discrepancy arises:

1. **Binance** runs a central limit order book with continuous matching. Prices update in microseconds as new orders arrive.

2. **Raydium** (or any AMM) prices assets according to the constant-product formula. The on-chain price only changes when a swap transaction actually lands in a block.

3. Between Solana slots (~400ms apart), the Binance price can move significantly. The on-chain price is "stale" relative to the CEX price during this window.

4. A searcher monitoring both prices simultaneously can detect when the stale on-chain price is far enough from the live CEX price to be profitable after fees.

5. The searcher submits a swap transaction (often via a Jito bundle) to capture the discrepancy before the next large trade naturally corrects it.

The gap closes naturally through arbitrage — each successful arb trade pushes the on-chain price closer to the CEX price. In liquid markets, the gap is typically captured within a few slots.

### Why It Is Not Risk-Free

CEX-DEX arb is sometimes described as "free money," but this overstates the case. Real risks include:

- **Execution risk**: your transaction may not land if the leader does not include it, or if another searcher gets there first
- **Slippage**: large positions move the pool price against you during execution
- **Fee risk**: priority fees and Jito tips can exceed profit for small spreads
- **Latency risk**: if your price feed has higher latency than competitors, you will only see opportunities they have already taken
- **Smart contract risk**: bugs in the DEX program or the arb program can cause losses

mev-kit's simulation layer (`RPCSimulator`) gates every opportunity through a transaction simulation before executing. This catches many failure modes before they cost real money.

---

## Further Reading

- [Jito documentation](https://docs.jito.wtf)
- [Raydium AMM documentation](https://docs.raydium.io)
- [Solana validator architecture](https://docs.solana.com/validator/anatomy)
- [Helius — understanding Solana transactions](https://www.helius.dev/blog)
- [Guide 2: How CEX-DEX Arbitrage Works](./02-cex-dex-arb.md)
- [Guide 3: The mev-kit Pipeline](./03-pipeline.md)
