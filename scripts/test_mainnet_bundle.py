"""End-to-end mainnet test — submit a real Jito bundle.

This script submits a tiny swap (0.001 SOL) to verify the full
execution pipeline works on mainnet. It costs real SOL (gas + tip).

Usage:
    export HELIUS_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_KEY
    export WALLET_KEYPAIR_PATH=/path/to/keypair.json
    python scripts/test_mainnet_bundle.py --dry-run  # Validate without submitting
    python scripts/test_mainnet_bundle.py             # Actually submit
"""

import asyncio
import json
import os
import sys

import click
import httpx

from mev_kit.utils.transaction_builder import (
    SOL_USDC_RAYDIUM,
    build_bundle_transactions,
)


@click.command()
@click.option("--dry-run", is_flag=True, help="Build bundle but don't submit")
@click.option(
    "--amount", default=1_000_000, help="Amount in lamports (default: 0.001 SOL)"
)
@click.option(
    "--tip", default=10_000, help="Tip in lamports (default: 0.00001 SOL)"
)
def main(dry_run: bool, amount: int, tip: int) -> None:
    """Submit a test Jito bundle to mainnet."""
    asyncio.run(run_test(dry_run, amount, tip))


async def run_test(dry_run: bool, amount: int, tip: int) -> None:
    """Build and optionally submit a Jito bundle on mainnet.

    Args:
        dry_run: If True, build the bundle but skip submission.
        amount: Swap amount in lamports.
        tip: Jito tip amount in lamports.
    """
    rpc_url = os.environ.get("HELIUS_RPC_URL")
    keypair_path = os.environ.get("WALLET_KEYPAIR_PATH")

    if not rpc_url:
        click.echo("Error: HELIUS_RPC_URL not set")
        sys.exit(1)
    if not keypair_path:
        click.echo("Error: WALLET_KEYPAIR_PATH not set")
        sys.exit(1)

    from solders.keypair import Keypair

    with open(keypair_path) as f:
        keypair = Keypair.from_bytes(bytes(json.load(f)))

    click.echo(f"Wallet: {keypair.pubkey()}")
    click.echo(f"Amount: {amount} lamports ({amount / 1e9:.6f} SOL)")
    click.echo(f"Tip: {tip} lamports ({tip / 1e9:.6f} SOL)")

    pool = SOL_USDC_RAYDIUM
    click.echo(f"Pool: {pool['amm_id']}")

    # Build bundle
    click.echo("\nBuilding bundle...")
    try:
        transactions = await build_bundle_transactions(
            pool_accounts=pool,
            keypair=keypair,
            amount_in=amount,
            minimum_amount_out=0,
            tip_lamports=tip,
            rpc_url=rpc_url,
        )
        click.echo(f"  Swap tx: {len(transactions[0])} bytes (base64)")
        click.echo(f"  Tip tx: {len(transactions[1])} bytes (base64)")
    except Exception as exc:
        click.echo(f"  Build failed: {exc}")
        sys.exit(1)

    if dry_run:
        click.echo("\n[DRY RUN] Bundle built successfully. Not submitting.")
        click.echo("Run without --dry-run to actually submit to Jito.")
        return

    # Submit to Jito
    jito_url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
    click.echo(f"\nSubmitting to {jito_url}...")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            jito_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [transactions],
            },
        )

        result = resp.json()
        if result.get("error"):
            click.echo(f"  Jito error: {result['error']}")
        else:
            bundle_id = result.get("result", "unknown")
            click.echo(f"  Bundle submitted! ID: {bundle_id}")
            click.echo("  Check status at: https://explorer.jito.wtf/")


if __name__ == "__main__":
    main()
