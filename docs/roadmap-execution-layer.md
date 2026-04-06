# Execution Layer Roadmap

**Goal:** Replace the three placeholder stubs so mev-kit can actually submit transactions on Solana.

**Current state:** The research/backtest side works. The execution side has the right interfaces but the implementations are placeholder JSON, not real Solana transactions.

---

## Item 1: Real Jito Bundle Construction

**File:** `src/mev_kit/adapters/sinks/jito_bundle.py`

**Current:** `build_bundle()` returns `{"transactions": [json.dumps(swap_dict), json.dumps(tip_dict)]}` — JSON objects, not real transactions. Submitting this to Jito will fail.

**Target:** Build real Solana transactions using `solders`, sign them with the user's keypair, serialize to base64, and submit via Jito's `sendBundle` JSON-RPC.

### Steps

**1.1 Build the swap instruction (Raydium AMM v4)**

The Raydium AMM swap instruction requires:
- Program ID: `675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8`
- 18 account keys (AMM, pool vaults, user token accounts, etc.)
- Instruction data: `swap_base_in` discriminator + `amount_in` + `minimum_amount_out` (u64 LE)

```python
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.message import Message
from solders.keypair import Keypair
import struct

RAYDIUM_AMM_PROGRAM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

def build_raydium_swap_ix(
    amm_id: Pubkey,
    amm_authority: Pubkey,
    amm_open_orders: Pubkey,
    amm_target_orders: Pubkey,
    pool_coin_vault: Pubkey,
    pool_pc_vault: Pubkey,
    serum_program: Pubkey,
    serum_market: Pubkey,
    serum_bids: Pubkey,
    serum_asks: Pubkey,
    serum_event_queue: Pubkey,
    serum_coin_vault: Pubkey,
    serum_pc_vault: Pubkey,
    serum_vault_signer: Pubkey,
    user_source: Pubkey,
    user_dest: Pubkey,
    user_owner: Pubkey,
    amount_in: int,
    minimum_amount_out: int,
) -> Instruction:
    # swap_base_in discriminator = 9 (from Raydium IDL)
    data = struct.pack("<BQQ", 9, amount_in, minimum_amount_out)
    
    accounts = [
        AccountMeta(Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"), False, False),  # SPL Token
        AccountMeta(amm_id, True, False),
        AccountMeta(amm_authority, False, False),
        AccountMeta(amm_open_orders, True, False),
        AccountMeta(amm_target_orders, True, False),
        AccountMeta(pool_coin_vault, True, False),
        AccountMeta(pool_pc_vault, True, False),
        AccountMeta(serum_program, False, False),
        AccountMeta(serum_market, True, False),
        AccountMeta(serum_bids, True, False),
        AccountMeta(serum_asks, True, False),
        AccountMeta(serum_event_queue, True, False),
        AccountMeta(serum_coin_vault, True, False),
        AccountMeta(serum_pc_vault, True, False),
        AccountMeta(serum_vault_signer, False, False),
        AccountMeta(user_source, True, False),
        AccountMeta(user_dest, True, False),
        AccountMeta(user_owner, True, True),  # signer
    ]
    
    return Instruction(RAYDIUM_AMM_PROGRAM, data, accounts)
```

**Challenge:** The 18 account addresses for a specific pool must be fetched on-chain or from a lookup table. For SOL/USDC Raydium, these are known constants. For dynamic pools, requires a `getAccountInfo` call to read the AMM state.

**Approach:** Start with hardcoded SOL/USDC account addresses (the most common MEV pair). Add dynamic lookup later.

**1.2 Build the tip instruction**

```python
from solders.system_program import transfer, TransferParams

JITO_TIP_ACCOUNTS = [
    Pubkey.from_string("HFqU5x63VTqvQss8hp11i4bPuSPGQzLJXnjg2vavp1iU"),
    # ... 7 more
]

def build_tip_ix(payer: Pubkey, tip_lamports: int) -> Instruction:
    tip_account = random.choice(JITO_TIP_ACCOUNTS)
    return transfer(TransferParams(
        from_pubkey=payer,
        to_pubkey=tip_account,
        lamports=tip_lamports,
    ))
```

**1.3 Assemble the bundle**

```python
async def build_real_bundle(
    swap_ix: Instruction,
    tip_ix: Instruction,
    keypair: Keypair,
    recent_blockhash: str,
) -> list[str]:
    # Transaction 1: swap
    swap_msg = Message.new_with_blockhash([swap_ix], keypair.pubkey(), Hash.from_string(recent_blockhash))
    swap_tx = Transaction.new_unsigned(swap_msg)
    swap_tx.sign([keypair], Hash.from_string(recent_blockhash))
    
    # Transaction 2: tip  
    tip_msg = Message.new_with_blockhash([tip_ix], keypair.pubkey(), Hash.from_string(recent_blockhash))
    tip_tx = Transaction.new_unsigned(tip_msg)
    tip_tx.sign([keypair], Hash.from_string(recent_blockhash))
    
    # Serialize to base64
    return [
        base64.b64encode(bytes(swap_tx)).decode(),
        base64.b64encode(bytes(tip_tx)).decode(),
    ]
```

**1.4 Submit to Jito block engine**

The existing `_submit_bundle` method is almost correct — it POSTs to the Jito endpoint. Just needs real base64 transactions instead of JSON strings.

**1.5 Testing**

- Unit test: build a swap instruction, verify it has 18 accounts and correct data layout
- Unit test: build a tip instruction, verify it's a system transfer to a Jito account
- Unit test: assemble bundle, verify 2 transactions, both base64-encoded
- Integration test (testnet): submit a bundle to Jito testnet and verify response format
- Dry run test: verify `dry_run=True` still skips submission

**Dependencies:**
- `solders` (already installed)
- Pool account addresses for SOL/USDC Raydium (can be hardcoded initially)
- A recent blockhash (from `getLatestBlockhash` RPC call)
- User's keypair (loaded from `WALLET_KEYPAIR_PATH`)

**Estimated effort:** 3-4 days

---

## Item 2: Real RPC Simulator

**File:** `src/mev_kit/adapters/simulators/rpc_simulator.py`

**Current:** Sends an empty string `""` as the transaction in `simulateTransaction`. The RPC returns an error or meaningless result.

**Target:** Build the actual swap transaction (same as Item 1), then call `simulateTransaction` to check if it would succeed and what the output amount would be.

### Steps

**2.1 Reuse the swap instruction builder from Item 1**

The RPC simulator needs the same `build_raydium_swap_ix()` function. Extract it into a shared module `src/mev_kit/utils/transaction_builder.py`.

**2.2 Build a simulation-ready transaction**

```python
async def build_simulation_tx(
    opportunity: Opportunity,
    rpc_url: str,
) -> str:
    """Build a swap transaction for simulation (not signing needed)."""
    # 1. Get recent blockhash
    blockhash = await get_latest_blockhash(rpc_url)
    
    # 2. Build swap instruction
    swap_ix = build_raydium_swap_ix(
        amm_id=Pubkey.from_string(opportunity.pool_address),
        amount_in=opportunity.amount_in_lamports,
        minimum_amount_out=0,  # For simulation, accept any output
        # ... pool-specific accounts
    )
    
    # 3. Use a dummy signer for simulation
    dummy = Keypair()
    msg = Message.new_with_blockhash([swap_ix], dummy.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([dummy], blockhash)
    
    # 4. Return base64-encoded
    return base64.b64encode(bytes(tx)).decode()
```

**2.3 Call simulateTransaction with real transaction**

Replace the empty string in `_call_simulate_transaction`:

```python
async def _call_simulate_transaction(self, opportunity: Opportunity) -> dict:
    tx_base64 = await build_simulation_tx(opportunity, self.rpc_url)
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "simulateTransaction",
        "params": [
            tx_base64,
            {
                "encoding": "base64",
                "commitment": "processed",
                "replaceRecentBlockhash": True,
            },
        ],
    }
    
    response = await self._client.post(self.rpc_url, json=payload)
    response.raise_for_status()
    return response.json()
```

**2.4 Parse simulation results for profit calculation**

The simulation response includes `logs` which contain the actual swap output. Parse the Raydium swap log to extract `amount_out`:

```python
def parse_swap_output_from_logs(logs: list[str]) -> int | None:
    """Extract swap output amount from Raydium program logs."""
    for log in logs:
        if "ray_log" in log:
            # Raydium logs the swap result in base64-encoded format
            # Decode and extract output amount
            ...
    return None
```

**Alternative approach:** Use `accounts` field in simulation request to get pre/post token balances, then compute output from the delta.

**2.5 Testing**

- Unit test: verify transaction construction produces valid base64
- Unit test: mock RPC response with realistic simulation result, verify profit parsing
- Integration test (devnet): submit simulation against Solana devnet and verify response

**Dependencies:**
- Same as Item 1 (shared transaction builder)
- RPC endpoint (Helius free tier works for simulation)
- Pool account addresses

**Estimated effort:** 2-3 days

---

## Item 3: Dynamic Strategy Selection in CLI

**File:** `src/mev_kit/cli.py`

**Current state:** Already fixed in the latest commit — CLI `backtest` now uses `_load_detector()` and `FillSimulator`. But `paper` and `live` commands still hardcode `CEXDEXArbDetector`.

### Steps

**3.1 Fix paper command**

The `_run_paper()` function hardcodes:
```python
detector = CEXDEXArbDetector({...})
```

Replace with:
```python
from mev_kit.ui.backtest_runner import _load_detector
detector = _load_detector(config.strategy, {...})
```

**3.2 Fix live command**

Same change in `_run_live()`.

**3.3 Add --strategy CLI option**

```python
@main.command()
@click.option("--config", "-c", default="config/free.toml")
@click.option("--strategy", "-s", default=None, help="Strategy name (default: from config)")
@click.option("--data", "-d", required=True)
def backtest(config: str, strategy: str | None, data: str) -> None:
```

If `--strategy` is passed, override the config's strategy field.

**3.4 Testing**

- Test: `mev-kit backtest --strategy price_momentum --data file.parquet` uses the right detector
- Test: `mev-kit paper --strategy spread_tracker` loads the right detector

**Estimated effort:** 0.5 day (mostly done already)

---

## Shared dependency: Transaction Builder Module

**File:** `src/mev_kit/utils/transaction_builder.py`

Both Items 1 and 2 need a shared module for:
- Building Raydium AMM swap instructions
- Fetching pool account addresses (initially hardcoded for SOL/USDC, later dynamic)
- Getting recent blockhash
- Building tip instructions

### Pool account lookup

For SOL/USDC Raydium AMM v4, the accounts are known constants:

```python
SOL_USDC_POOL = {
    "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
    "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
    "amm_open_orders": "HRk9CMrpq7Fo9csehKVUVLfDk86RjWqv1VfMrLvVqkHb",
    "pool_coin_vault": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",
    "pool_pc_vault": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",
    # ... etc
}
```

For dynamic pool support (future): call `getAccountInfo` on the AMM account and parse the Raydium state layout to extract vault addresses.

**Estimated effort for shared module:** 1 day

---

## Execution order

```
1. Transaction Builder module (1 day)
     ↓
2. RPC Simulator — real simulation (2-3 days)    Item 1: Jito Bundles — real execution (3-4 days)
     ↓                                                    ↓
3. CLI paper/live strategy selection (0.5 day)   (can run in parallel with Item 2)
     ↓
4. Integration testing against devnet (1 day)
     ↓
5. Update README to remove "stub" warnings for completed items
```

**Total: 8-10 days of focused work.**

After this, mev-kit earns the right to say "execution-ready" in the README.
