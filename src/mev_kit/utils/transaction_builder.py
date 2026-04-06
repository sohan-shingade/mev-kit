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


# ---------------------------------------------------------------------------
# Pool lookup
# ---------------------------------------------------------------------------


def get_pool_accounts(pool_address: str) -> dict[str, str] | None:
    """Look up pool accounts by AMM address.

    Args:
        pool_address: The Raydium AMM pool address.

    Returns:
        Dict of account name to address, or None if the pool is unknown.
    """
    return _KNOWN_POOLS.get(pool_address)


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
