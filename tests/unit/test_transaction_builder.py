"""Tests for the transaction builder module."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from mev_kit.utils.transaction_builder import (
    JITO_TIP_ACCOUNTS,
    SOL_USDC_RAYDIUM,
    SWAP_BASE_IN_DISCRIMINATOR,
    build_raydium_swap_ix,
    build_tip_ix,
    get_pool_accounts,
)


# ---------------------------------------------------------------------------
# get_pool_accounts
# ---------------------------------------------------------------------------


class TestGetPoolAccounts:
    """Tests for pool account lookup."""

    def test_known_pool_returns_accounts(self) -> None:
        """SOL/USDC Raydium AMM returns the full account dict."""
        result = get_pool_accounts("58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2")
        assert result is not None
        assert result["amm_id"] == "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
        assert "amm_authority" in result
        assert "pool_coin_vault" in result
        assert "serum_market" in result

    def test_unknown_pool_returns_none(self) -> None:
        """An unknown pool address returns None."""
        assert get_pool_accounts("unknown") is None

    def test_unknown_valid_pubkey_returns_none(self) -> None:
        """A valid but unregistered pubkey returns None."""
        kp = Keypair()
        assert get_pool_accounts(str(kp.pubkey())) is None


# ---------------------------------------------------------------------------
# build_raydium_swap_ix
# ---------------------------------------------------------------------------


class TestBuildRaydiumSwapIx:
    """Tests for Raydium AMM v4 swap instruction construction."""

    def _build_ix(
        self, amount_in: int = 1_000_000, minimum_amount_out: int = 500_000
    ):
        kp = Keypair()
        return build_raydium_swap_ix(
            pool_accounts=SOL_USDC_RAYDIUM,
            user_source=kp.pubkey(),
            user_dest=kp.pubkey(),
            user_owner=kp.pubkey(),
            amount_in=amount_in,
            minimum_amount_out=minimum_amount_out,
        )

    def test_has_18_accounts(self) -> None:
        """Raydium AMM v4 swap requires exactly 18 account keys."""
        ix = self._build_ix()
        assert len(ix.accounts) == 18

    def test_discriminator_is_9(self) -> None:
        """swap_base_in discriminator byte must be 9."""
        ix = self._build_ix()
        assert ix.data[0] == SWAP_BASE_IN_DISCRIMINATOR
        assert ix.data[0] == 9

    def test_data_contains_amount_in_and_min_out(self) -> None:
        """Instruction data encodes amount_in and minimum_amount_out as u64 LE."""
        amount_in = 2_500_000
        min_out = 1_200_000
        ix = self._build_ix(amount_in=amount_in, minimum_amount_out=min_out)

        # Data layout: u8 discriminator + u64 amount_in + u64 min_out = 17 bytes
        assert len(ix.data) == 17

        disc, decoded_in, decoded_out = struct.unpack("<BQQ", bytes(ix.data))
        assert disc == 9
        assert decoded_in == amount_in
        assert decoded_out == min_out

    def test_program_id_is_raydium(self) -> None:
        """Instruction targets the Raydium AMM v4 program."""
        ix = self._build_ix()
        expected = Pubkey.from_string(
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
        )
        assert ix.program_id == expected

    def test_first_account_is_spl_token(self) -> None:
        """First account in layout is the SPL Token program (read-only)."""
        ix = self._build_ix()
        spl_token = Pubkey.from_string(
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        )
        assert ix.accounts[0].pubkey == spl_token
        assert ix.accounts[0].is_signer is False
        assert ix.accounts[0].is_writable is False

    def test_user_owner_is_signer(self) -> None:
        """The user_owner account (index 17) must be a signer."""
        ix = self._build_ix()
        user_owner_meta = ix.accounts[17]
        assert user_owner_meta.is_signer is True

    def test_pool_vaults_are_writable(self) -> None:
        """Pool coin and PC vaults must be writable."""
        ix = self._build_ix()
        # Index 5 = pool_coin_vault, Index 6 = pool_pc_vault
        assert ix.accounts[5].is_writable is True
        assert ix.accounts[6].is_writable is True

    def test_zero_amounts(self) -> None:
        """Zero amounts produce valid instruction data."""
        ix = self._build_ix(amount_in=0, minimum_amount_out=0)
        disc, amt_in, min_out = struct.unpack("<BQQ", bytes(ix.data))
        assert amt_in == 0
        assert min_out == 0


# ---------------------------------------------------------------------------
# build_tip_ix
# ---------------------------------------------------------------------------


class TestBuildTipIx:
    """Tests for Jito tip instruction construction."""

    def test_produces_system_transfer(self) -> None:
        """Tip instruction is a system program transfer."""
        kp = Keypair()
        ix = build_tip_ix(kp.pubkey(), 10_000)

        system_program = Pubkey.from_string(
            "11111111111111111111111111111111"
        )
        assert ix.program_id == system_program

    def test_has_two_accounts(self) -> None:
        """Transfer instruction has exactly 2 accounts (from, to)."""
        kp = Keypair()
        ix = build_tip_ix(kp.pubkey(), 10_000)
        assert len(ix.accounts) == 2

    def test_transfers_to_known_jito_account(self) -> None:
        """Destination is one of the known Jito tip accounts."""
        kp = Keypair()
        ix = build_tip_ix(kp.pubkey(), 10_000)
        to_pubkey = ix.accounts[1].pubkey
        assert to_pubkey in JITO_TIP_ACCOUNTS

    def test_payer_is_from_account(self) -> None:
        """The payer pubkey is the source (from) account."""
        kp = Keypair()
        ix = build_tip_ix(kp.pubkey(), 50_000)
        assert ix.accounts[0].pubkey == kp.pubkey()

    def test_from_account_is_signer_and_writable(self) -> None:
        """The from account must be both a signer and writable."""
        kp = Keypair()
        ix = build_tip_ix(kp.pubkey(), 10_000)
        assert ix.accounts[0].is_signer is True
        assert ix.accounts[0].is_writable is True
