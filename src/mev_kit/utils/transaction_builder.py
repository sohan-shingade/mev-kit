"""Transaction Builder — shared module for building real Solana transactions.

Builds Raydium AMM v4 swap instructions, Jito tip instructions, and
assembles signed transactions using the solders library. Shared by both
the RPC Simulator (simulation) and the Jito Bundle Sink (live execution).

Pool account addresses are hardcoded for known pools (starting with
SOL/USDC Raydium). Dynamic lookup can be added later via on-chain
getAccountInfo calls.
"""

from __future__ import annotations

import base64
import random
import struct

import httpx
import structlog
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAYDIUM_AMM_PROGRAM = Pubkey.from_string(
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
)
SPL_TOKEN_PROGRAM = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)

# Jito tip accounts — one is chosen at random per bundle.
JITO_TIP_ACCOUNTS = [
    Pubkey.from_string("HFqU5x63VTqvQss8hp11i4bPuSPGQzLJXnjg2vavp1iU"),
    Pubkey.from_string("Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY"),
    Pubkey.from_string("DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh"),
    Pubkey.from_string("ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt"),
    Pubkey.from_string("DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL"),
    Pubkey.from_string("3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"),
    Pubkey.from_string("96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"),
]

# Raydium swap_base_in discriminator byte
SWAP_BASE_IN_DISCRIMINATOR = 9

# ---------------------------------------------------------------------------
# Known pool account registries
# ---------------------------------------------------------------------------

SOL_USDC_RAYDIUM: dict[str, str] = {
    "amm_id": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
    "amm_authority": "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
    "amm_open_orders": "HRk9CMrpq7Fo9csehKVUVLfDk86RjWqv1VfMrLvVqkHb",
    "amm_target_orders": "CZza3Ej4Mc58MnxWA385itCC9jCo3L1D7zc3LKy1bZMR",
    "pool_coin_vault": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",
    "pool_pc_vault": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",
    "serum_program": "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",
    "serum_market": "9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT",
    "serum_bids": "14ivtgssEBoBjuZJtSAPKYgpUK7DmnSwuPMqJoVTSgKJ",
    "serum_asks": "CEQdAFKdycHugujQg9k2wbmxjcqQ5HQo3LB2PoHFyhP2",
    "serum_event_queue": "5KKsLVU6TcbVDK4BS6K1DGDxnh4Q9xjYJ8XaDCG5t8ht",
    "serum_coin_vault": "36c6YqAwyGKQG66XEp2dJc5JqjaBNv7sVghEtJv4c7u6",
    "serum_pc_vault": "8CFo8bL8mZQK8abbFyypFMwEDMVoqRfm8v5J1PJHzGS8",
    "serum_vault_signer": "F8Vyqk3unwxkXukZFQeYyGmFfTG3CAX4v24iyrjEYBJV",
}

# Registry mapping AMM address to pool accounts
_KNOWN_POOLS: dict[str, dict[str, str]] = {
    SOL_USDC_RAYDIUM["amm_id"]: SOL_USDC_RAYDIUM,
}


# Cache for dynamically fetched pool accounts
_dynamic_pool_cache: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Pool lookup
# ---------------------------------------------------------------------------


def get_pool_accounts(pool_address: str) -> dict[str, str] | None:
    """Look up pool accounts. Checks registry first, then dynamic cache.

    Args:
        pool_address: The Raydium AMM pool address.

    Returns:
        Dict of account name to address, or None if the pool is unknown.
    """
    # Check hardcoded registry
    result = _KNOWN_POOLS.get(pool_address)
    if result:
        return result
    # Check dynamic cache
    return _dynamic_pool_cache.get(pool_address)


async def fetch_pool_accounts(amm_id: str, rpc_url: str) -> dict[str, str] | None:
    """Fetch Raydium AMM v4 pool account addresses from on-chain state.

    Reads the AMM account data and extracts vault addresses, market info,
    and authority from the account layout.

    Raydium AMM v4 state layout (key offsets):
    - bytes 0-7: status/nonce
    - bytes 8-39: various config
    - offset 64: coin_vault (Pubkey, 32 bytes)
    - offset 96: pc_vault (Pubkey, 32 bytes)
    - offset 128: lp_mint (Pubkey, 32 bytes)
    - offset 160: coin_mint (Pubkey, 32 bytes)
    - offset 192: pc_mint (Pubkey, 32 bytes)
    - offset 272: open_orders (Pubkey, 32 bytes)
    - offset 304: market (Pubkey, 32 bytes)
    - offset 336: market_program (Pubkey, 32 bytes)
    - offset 368: target_orders (Pubkey, 32 bytes)

    Note: The exact offsets may vary. The above are approximate for AMM v4.
    For production use, parse the full IDL layout.

    Args:
        amm_id: The Raydium AMM pool address (base58).
        rpc_url: Solana JSON-RPC endpoint URL.

    Returns:
        Dict of account name to address, or None on failure.
    """
    import base64 as b64_mod

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(rpc_url, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [amm_id, {"encoding": "base64"}],
            })
            resp.raise_for_status()
            data = resp.json()

            value = data.get("result", {}).get("value")
            if not value or not value.get("data"):
                return None

            raw = b64_mod.b64decode(value["data"][0])

            if len(raw) < 400:
                return None

            def read_pubkey(offset: int) -> str:
                return str(Pubkey.from_bytes(raw[offset:offset + 32]))

            # Extract key accounts from AMM state
            # These offsets are for Raydium AMM v4
            coin_vault = read_pubkey(64)
            pc_vault = read_pubkey(96)
            coin_mint = read_pubkey(160)
            pc_mint = read_pubkey(192)
            open_orders = read_pubkey(272)
            market = read_pubkey(304)
            market_program = read_pubkey(336)
            target_orders = read_pubkey(368)

            # AMM authority is a PDA
            amm_authority = str(Pubkey.find_program_address(
                [bytes([97, 109, 109, 32, 97, 117, 116, 104, 111, 114, 105, 116, 121])],  # "amm authority"
                RAYDIUM_AMM_PROGRAM,
            )[0])

            return {
                "amm_id": amm_id,
                "amm_authority": amm_authority,
                "amm_open_orders": open_orders,
                "amm_target_orders": target_orders,
                "pool_coin_vault": coin_vault,
                "pool_pc_vault": pc_vault,
                "serum_program": market_program,
                "serum_market": market,
                # Serum market accounts need a separate lookup
                # For now, leave these empty — they're required for the swap
                # but we can't derive them from the AMM state alone
                "serum_bids": "",
                "serum_asks": "",
                "serum_event_queue": "",
                "serum_coin_vault": "",
                "serum_pc_vault": "",
                "serum_vault_signer": "",
                "coin_mint": coin_mint,
                "pc_mint": pc_mint,
            }
    except Exception as exc:
        logger.warning(
            "transaction_builder.fetch_pool_failed",
            error=str(exc),
            amm_id=amm_id,
        )
        return None


async def get_pool_accounts_async(
    pool_address: str, rpc_url: str
) -> dict[str, str] | None:
    """Look up pool accounts with dynamic on-chain fallback.

    Checks the hardcoded registry and dynamic cache first.
    If the pool is not found, fetches account data from chain
    and caches the result.

    Args:
        pool_address: The Raydium AMM pool address.
        rpc_url: Solana JSON-RPC endpoint URL.

    Returns:
        Dict of account name to address, or None if lookup fails.
    """
    # Check registry and cache
    result = get_pool_accounts(pool_address)
    if result:
        return result

    # Try dynamic fetch
    accounts = await fetch_pool_accounts(pool_address, rpc_url)
    if accounts:
        _dynamic_pool_cache[pool_address] = accounts
        return accounts

    return None


# ---------------------------------------------------------------------------
# Instruction builders
# ---------------------------------------------------------------------------


def build_raydium_swap_ix(
    pool_accounts: dict[str, str],
    user_source: Pubkey,
    user_dest: Pubkey,
    user_owner: Pubkey,
    amount_in: int,
    minimum_amount_out: int,
) -> Instruction:
    """Build a Raydium AMM v4 swap_base_in instruction.

    The instruction has the standard 18-account layout required by the
    Raydium AMM v4 program for a swap_base_in operation.

    Args:
        pool_accounts: Dict mapping account names to base58 address strings.
        user_source: User's source token account (token being sold).
        user_dest: User's destination token account (token being bought).
        user_owner: User's wallet (signer).
        amount_in: Amount of input token in smallest unit (lamports for SOL).
        minimum_amount_out: Minimum acceptable output amount (slippage protection).

    Returns:
        A solders Instruction with 18 accounts and the swap_base_in data layout.
    """
    # Instruction data: discriminator (u8) + amount_in (u64 LE) + min_out (u64 LE)
    data = struct.pack(
        "<BQQ", SWAP_BASE_IN_DISCRIMINATOR, amount_in, minimum_amount_out
    )

    # 18-account layout per Raydium AMM v4 spec
    # AccountMeta(pubkey, is_signer, is_writable)
    accounts = [
        AccountMeta(SPL_TOKEN_PROGRAM, False, False),                                         # 0: SPL Token program
        AccountMeta(Pubkey.from_string(pool_accounts["amm_id"]), False, True),                # 1: AMM account
        AccountMeta(Pubkey.from_string(pool_accounts["amm_authority"]), False, False),        # 2: AMM authority (PDA)
        AccountMeta(Pubkey.from_string(pool_accounts["amm_open_orders"]), False, True),       # 3: AMM open orders
        AccountMeta(Pubkey.from_string(pool_accounts["amm_target_orders"]), False, True),     # 4: AMM target orders
        AccountMeta(Pubkey.from_string(pool_accounts["pool_coin_vault"]), False, True),       # 5: Pool coin vault
        AccountMeta(Pubkey.from_string(pool_accounts["pool_pc_vault"]), False, True),         # 6: Pool PC vault
        AccountMeta(Pubkey.from_string(pool_accounts["serum_program"]), False, False),        # 7: Serum DEX program
        AccountMeta(Pubkey.from_string(pool_accounts["serum_market"]), False, True),          # 8: Serum market
        AccountMeta(Pubkey.from_string(pool_accounts["serum_bids"]), False, True),            # 9: Serum bids
        AccountMeta(Pubkey.from_string(pool_accounts["serum_asks"]), False, True),            # 10: Serum asks
        AccountMeta(Pubkey.from_string(pool_accounts["serum_event_queue"]), False, True),     # 11: Serum event queue
        AccountMeta(Pubkey.from_string(pool_accounts["serum_coin_vault"]), False, True),      # 12: Serum coin vault
        AccountMeta(Pubkey.from_string(pool_accounts["serum_pc_vault"]), False, True),        # 13: Serum PC vault
        AccountMeta(Pubkey.from_string(pool_accounts["serum_vault_signer"]), False, False),   # 14: Serum vault signer
        AccountMeta(user_source, False, True),                                                # 15: User source token acct
        AccountMeta(user_dest, False, True),                                                  # 16: User dest token acct
        AccountMeta(user_owner, True, False),                                                 # 17: User wallet (signer)
    ]

    return Instruction(RAYDIUM_AMM_PROGRAM, data, accounts)


def build_tip_ix(payer: Pubkey, tip_lamports: int) -> Instruction:
    """Build a Jito tip transfer instruction.

    Selects a random Jito tip account and creates a system transfer
    instruction to send the specified tip amount.

    Args:
        payer: The wallet pubkey that will pay the tip.
        tip_lamports: Amount to tip in lamports.

    Returns:
        A system program transfer Instruction.
    """
    tip_account = random.choice(JITO_TIP_ACCOUNTS)
    return transfer(
        TransferParams(
            from_pubkey=payer,
            to_pubkey=tip_account,
            lamports=tip_lamports,
        )
    )


# ---------------------------------------------------------------------------
# Blockhash fetching
# ---------------------------------------------------------------------------


async def get_recent_blockhash(rpc_url: str) -> Hash:
    """Fetch the latest blockhash from Solana RPC.

    Args:
        rpc_url: Solana JSON-RPC endpoint URL.

    Returns:
        A solders Hash representing the recent blockhash.

    Raises:
        RuntimeError: If the RPC call fails or returns an unexpected response.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "finalized"}],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(rpc_url, json=payload)
        response.raise_for_status()
        data = response.json()

    result = data.get("result")
    if result is None:
        error = data.get("error", {})
        raise RuntimeError(f"getLatestBlockhash failed: {error}")

    blockhash_str = result["value"]["blockhash"]
    return Hash.from_string(blockhash_str)


# ---------------------------------------------------------------------------
# Full transaction builders
# ---------------------------------------------------------------------------


async def build_swap_transaction(
    pool_accounts: dict[str, str],
    keypair: Keypair,
    amount_in: int,
    minimum_amount_out: int,
    rpc_url: str,
) -> bytes:
    """Build a complete signed swap transaction.

    Fetches a recent blockhash, constructs the Raydium swap instruction,
    assembles a Transaction, signs it, and returns the serialized bytes.

    Note: user_source and user_dest are set to the keypair's pubkey as
    placeholders. In production, these should be the user's associated
    token accounts for the input and output mints.

    Args:
        pool_accounts: Dict of pool account names to base58 addresses.
        keypair: Solana Keypair for signing.
        amount_in: Input amount in smallest denomination.
        minimum_amount_out: Minimum output amount (slippage).
        rpc_url: Solana RPC URL for blockhash fetch.

    Returns:
        Serialized transaction bytes.
    """
    blockhash = await get_recent_blockhash(rpc_url)

    swap_ix = build_raydium_swap_ix(
        pool_accounts=pool_accounts,
        user_source=keypair.pubkey(),  # placeholder — real impl uses ATA
        user_dest=keypair.pubkey(),    # placeholder — real impl uses ATA
        user_owner=keypair.pubkey(),
        amount_in=amount_in,
        minimum_amount_out=minimum_amount_out,
    )

    msg = Message.new_with_blockhash([swap_ix], keypair.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([keypair], blockhash)

    return bytes(tx)


async def build_bundle_transactions(
    pool_accounts: dict[str, str],
    keypair: Keypair,
    amount_in: int,
    minimum_amount_out: int,
    tip_lamports: int,
    rpc_url: str,
) -> list[str]:
    """Build swap + tip transactions for a Jito bundle.

    Creates two transactions:
        1. The Raydium AMM swap transaction
        2. A Jito tip transfer transaction

    Both are signed with the provided keypair and returned as
    base64-encoded strings suitable for Jito sendBundle submission.

    Args:
        pool_accounts: Dict of pool account names to base58 addresses.
        keypair: Solana Keypair for signing both transactions.
        amount_in: Input amount in smallest denomination.
        minimum_amount_out: Minimum output amount (slippage).
        tip_lamports: Jito tip amount in lamports.
        rpc_url: Solana RPC URL for blockhash fetch.

    Returns:
        List of two base64-encoded transaction strings [swap_tx, tip_tx].
    """
    blockhash = await get_recent_blockhash(rpc_url)

    # Transaction 1: Raydium swap
    swap_ix = build_raydium_swap_ix(
        pool_accounts=pool_accounts,
        user_source=keypair.pubkey(),
        user_dest=keypair.pubkey(),
        user_owner=keypair.pubkey(),
        amount_in=amount_in,
        minimum_amount_out=minimum_amount_out,
    )
    swap_msg = Message.new_with_blockhash([swap_ix], keypair.pubkey(), blockhash)
    swap_tx = Transaction.new_unsigned(swap_msg)
    swap_tx.sign([keypair], blockhash)

    # Transaction 2: Jito tip
    tip_ix = build_tip_ix(keypair.pubkey(), tip_lamports)
    tip_msg = Message.new_with_blockhash([tip_ix], keypair.pubkey(), blockhash)
    tip_tx = Transaction.new_unsigned(tip_msg)
    tip_tx.sign([keypair], blockhash)

    return [
        base64.b64encode(bytes(swap_tx)).decode(),
        base64.b64encode(bytes(tip_tx)).decode(),
    ]
