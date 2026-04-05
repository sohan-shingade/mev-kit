"""Comprehensive tests for the data fetching system.

Covers:
- Duration/interval parsing helpers
- Binance kline fetch logic (mocked httpx)
- Helius pool-state fetch logic (mocked httpx)
- API endpoint integration (FastAPI TestClient)
- End-to-end data pipeline: fetch → Parquet → preview → delete
"""

from __future__ import annotations

import base64
import os
import struct
import tempfile
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest
from fastapi.testclient import TestClient

from mev_kit.ui.routers.data import (
    _fetch_jobs,
    _parse_duration_to_minutes,
    _parse_duration_to_seconds,
    _run_binance_fetch,
    _run_helius_fetch,
)
from mev_kit.ui.server import create_app

# ---------------------------------------------------------------------------
# Shared fixtures & helpers
# ---------------------------------------------------------------------------

# Each kline: [open_time, open, high, low, close, volume, close_time, ...]
MOCK_KLINE = [
    1700000000000,  # open_time  (ms)
    "148.00",       # open
    "149.00",       # high
    "147.50",       # low
    "148.50",       # close
    "1000.0",       # volume
    1700000059999,  # close_time (ms)
    "148000.0",     # quote_volume
    100,            # trades
    "500.0",        # taker_buy_base
    "74000.0",      # taker_buy_quote
    "0",            # ignore
]


def _build_helius_response(base_lamports: int, quote_micro: int, slot: int = 280_000_000) -> dict:
    """Build a fake Helius RPC getAccountInfo response with AMM reserves packed at offsets 64/72."""
    data = bytearray(200)
    struct.pack_into("<Q", data, 64, base_lamports)
    struct.pack_into("<Q", data, 72, quote_micro)
    encoded = base64.b64encode(bytes(data)).decode()
    return {
        "jsonrpc": "2.0",
        "result": {
            "context": {"slot": slot},
            "value": {
                "data": [encoded, "base64"],
                "lamports": 1_000_000,
                "owner": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                "executable": False,
                "rentEpoch": 0,
            },
        },
        "id": 1,
    }


@pytest.fixture(autouse=True)
def clean_fetch_jobs():
    """Wipe _fetch_jobs before every test to prevent state leakage."""
    _fetch_jobs.clear()
    yield
    _fetch_jobs.clear()


@pytest.fixture
def client(tmp_path) -> TestClient:
    """TestClient wired to a temp data directory."""
    app = create_app(config_dir="config/", data_dir=str(tmp_path))
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Duration / interval parsing
# ---------------------------------------------------------------------------

class TestParseDurationToSeconds:

    def test_1m_is_60(self) -> None:
        assert _parse_duration_to_seconds("1m") == 60

    def test_5m_is_300(self) -> None:
        assert _parse_duration_to_seconds("5m") == 300

    def test_1h_is_3600(self) -> None:
        assert _parse_duration_to_seconds("1h") == 3600

    def test_1d_is_86400(self) -> None:
        assert _parse_duration_to_seconds("1d") == 86400

    def test_plain_int_is_seconds(self) -> None:
        assert _parse_duration_to_seconds("30") == 30

    def test_leading_trailing_whitespace(self) -> None:
        assert _parse_duration_to_seconds("  5m  ") == 300

    def test_invalid_string_returns_default(self) -> None:
        assert _parse_duration_to_seconds("abc", default=99) == 99

    def test_invalid_string_uses_builtin_default(self) -> None:
        assert _parse_duration_to_seconds("xyz") == 60

    def test_seconds_suffix(self) -> None:
        assert _parse_duration_to_seconds("45s") == 45

    def test_uppercase_is_coerced(self) -> None:
        # strip().lower() in the impl means "1M" → "1m"
        assert _parse_duration_to_seconds("1M") == 60


class TestParseDurationToMinutes:

    def test_1d_is_1440(self) -> None:
        assert _parse_duration_to_minutes("1d") == 1440

    def test_7d_is_10080(self) -> None:
        assert _parse_duration_to_minutes("7d") == 10080

    def test_1h_is_60(self) -> None:
        assert _parse_duration_to_minutes("1h") == 60

    def test_plain_int_is_minutes(self) -> None:
        assert _parse_duration_to_minutes("60") == 60

    def test_minutes_suffix(self) -> None:
        assert _parse_duration_to_minutes("30m") == 30

    def test_invalid_string_returns_default(self) -> None:
        assert _parse_duration_to_minutes("bad!", default=42) == 42

    def test_invalid_string_uses_builtin_default(self) -> None:
        assert _parse_duration_to_minutes("??") == 60

    def test_uppercase_coerced(self) -> None:
        assert _parse_duration_to_minutes("2H") == 120


# ---------------------------------------------------------------------------
# 2. Binance fetch logic
# ---------------------------------------------------------------------------

def _make_mock_client(responses: list) -> MagicMock:
    """Build a mock httpx.AsyncClient that returns responses in sequence."""
    mock_resp_list = []
    for r in responses:
        if isinstance(r, Exception):
            mock_resp_list.append(r)
        else:
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = r
            mock_resp_list.append(mock_resp)

    mock_client = AsyncMock()

    # Build a side_effect list for get()
    side_effects = []
    for item in mock_resp_list:
        if isinstance(item, Exception):
            side_effects.append(item)
        else:
            side_effects.append(item)

    mock_client.get = AsyncMock(side_effect=side_effects)
    mock_client.post = AsyncMock(side_effect=side_effects)
    return mock_client


class TestRunBinanceFetch:

    @pytest.mark.asyncio
    async def test_creates_parquet_with_correct_columns(self, tmp_path) -> None:
        job_id = "test_binance_basic"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [MOCK_KLINE] * 5

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        assert _fetch_jobs[job_id]["status"] == "completed"
        assert _fetch_jobs[job_id]["rows"] == 5

        parquet_files = list(tmp_path.glob("binance_*.parquet"))
        assert len(parquet_files) == 1

        df = pl.read_parquet(parquet_files[0])
        assert df.shape[0] == 5
        expected_cols = {"symbol", "price", "volume", "timestamp", "open", "high", "low", "close"}
        assert expected_cols.issubset(set(df.columns))

    @pytest.mark.asyncio
    async def test_empty_response_zero_rows(self, tmp_path) -> None:
        job_id = "test_binance_empty"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        assert _fetch_jobs[job_id]["status"] == "completed"
        assert _fetch_jobs[job_id]["rows"] == 0
        # No parquet file written for empty data
        assert list(tmp_path.glob("binance_*.parquet")) == []

    @pytest.mark.asyncio
    async def test_http_error_marks_job_error(self, tmp_path) -> None:
        job_id = "test_binance_http_error"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("HTTP 429 Too Many Requests"))

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        assert _fetch_jobs[job_id]["status"] == "error"
        assert "HTTP 429" in _fetch_jobs[job_id]["error"]

    @pytest.mark.asyncio
    async def test_pagination_combines_batches(self, tmp_path) -> None:
        """First call returns 1000 rows (full page), second returns 500 (partial = last page)."""
        job_id = "test_binance_paged"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        first_batch = [MOCK_KLINE[:] for _ in range(1000)]
        # Each kline needs a distinct open_time so start_time advances
        for idx, kline in enumerate(first_batch):
            kline = list(kline)
            kline[0] = 1700000000000 + idx * 60_000
            first_batch[idx] = kline

        second_batch = [MOCK_KLINE[:] for _ in range(500)]

        call_count = 0

        async def fake_get(url, params=None, **kwargs):
            nonlocal call_count
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if call_count == 0:
                mock_resp.json.return_value = first_batch
            else:
                mock_resp.json.return_value = second_batch
            call_count += 1
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _run_binance_fetch(job_id, "SOLUSDT", "1m", 2, str(tmp_path), use_us=False)

        assert _fetch_jobs[job_id]["status"] == "completed"
        assert _fetch_jobs[job_id]["rows"] == 1500
        parquet_files = list(tmp_path.glob("binance_*.parquet"))
        assert len(parquet_files) == 1
        df = pl.read_parquet(parquet_files[0])
        assert df.shape[0] == 1500

    @pytest.mark.asyncio
    async def test_start_time_advances_between_batches(self, tmp_path) -> None:
        """Verify startTime parameter advances past the last candle open_time."""
        job_id = "test_binance_advance"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        first_batch = []
        for i in range(1000):
            kline = list(MOCK_KLINE)
            kline[0] = 1700000000000 + i * 60_000  # open_time increments by 1 min
            first_batch.append(kline)

        second_batch = [list(MOCK_KLINE)]  # just one candle on second call

        captured_params: list[dict] = []

        async def fake_get(url, params=None, **kwargs):
            captured_params.append(dict(params or {}))
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            if len(captured_params) == 1:
                mock_resp.json.return_value = first_batch
            else:
                mock_resp.json.return_value = second_batch
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _run_binance_fetch(job_id, "SOLUSDT", "1m", 2, str(tmp_path), use_us=False)

        assert len(captured_params) == 2
        second_start = captured_params[1]["startTime"]

        # second_start should equal last open_time of batch 1 + 1 ms
        expected = first_batch[-1][0] + 1
        assert second_start == expected

    @pytest.mark.asyncio
    async def test_us_endpoint_used_when_flag_set(self, tmp_path) -> None:
        """use_us=True must point requests at api.binance.us."""
        job_id = "test_binance_us"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        captured_urls: list[str] = []

        async def fake_get(url, params=None, **kwargs):
            captured_urls.append(url)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [MOCK_KLINE]
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=True)

        assert len(captured_urls) >= 1
        assert all("binance.us" in u for u in captured_urls)

    @pytest.mark.asyncio
    async def test_non_us_endpoint_used_by_default(self, tmp_path) -> None:
        job_id = "test_binance_com"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        captured_urls: list[str] = []

        async def fake_get(url, params=None, **kwargs):
            captured_urls.append(url)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [MOCK_KLINE]
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = fake_get

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        assert all("binance.com" in u and "binance.us" not in u for u in captured_urls)

    @pytest.mark.asyncio
    async def test_parquet_column_values_correct(self, tmp_path) -> None:
        """Spot-check that column values are mapped correctly from kline fields."""
        job_id = "test_binance_values"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [MOCK_KLINE]

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        df = pl.read_parquet(list(tmp_path.glob("binance_*.parquet"))[0])
        row = df.row(0, named=True)

        assert row["symbol"] == "SOLUSDT"
        assert row["open"] == pytest.approx(148.00)
        assert row["high"] == pytest.approx(149.00)
        assert row["low"] == pytest.approx(147.50)
        assert row["close"] == pytest.approx(148.50)
        # price is mapped from candle[4] (close)
        assert row["price"] == pytest.approx(148.50)
        assert row["volume"] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# 3. Helius fetch logic
# ---------------------------------------------------------------------------

class TestRunHeliusFetch:

    @pytest.mark.asyncio
    async def test_creates_parquet_with_correct_columns(self, tmp_path) -> None:
        job_id = "test_helius_basic"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        helius_resp = _build_helius_response(
            base_lamports=1_000_000_000_000,  # 1000 SOL
            quote_micro=148_000_000_000,       # 148000 USDC
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = helius_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            # interval=60s, duration=1min → total_fetches = 1
            await _run_helius_fetch(
                job_id, "FakePoolAddr111", 60, 1, str(tmp_path), "fake_api_key"
            )

        assert _fetch_jobs[job_id]["status"] == "completed"
        assert _fetch_jobs[job_id]["rows"] == 1

        parquet_files = list(tmp_path.glob("raydium_*.parquet"))
        assert len(parquet_files) == 1

        df = pl.read_parquet(parquet_files[0])
        expected_cols = {
            "pool_address", "dex", "base_mint", "quote_mint",
            "base_reserve", "quote_reserve", "price", "fee_bps", "slot", "timestamp",
        }
        assert expected_cols.issubset(set(df.columns))

    @pytest.mark.asyncio
    async def test_price_calculation(self, tmp_path) -> None:
        """price = quote_reserve / base_reserve after unit conversion."""
        job_id = "test_helius_price"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        # 1000 SOL (lamports = 1e12), 148000 USDC (micro = 148e9)
        # base_reserve = 1e12 / 1e9 = 1000, quote_reserve = 148e9 / 1e6 = 148000
        # price = 148000 / 1000 = 148.0
        helius_resp = _build_helius_response(
            base_lamports=1_000_000_000_000,
            quote_micro=148_000_000_000,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = helius_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "FakePoolAddr111", 60, 1, str(tmp_path), "fake_api_key"
            )

        df = pl.read_parquet(list(tmp_path.glob("raydium_*.parquet"))[0])
        row = df.row(0, named=True)
        assert row["price"] == pytest.approx(148.0)
        assert row["base_reserve"] == pytest.approx(1000.0)
        assert row["quote_reserve"] == pytest.approx(148000.0)

    @pytest.mark.asyncio
    async def test_null_value_row_skipped(self, tmp_path) -> None:
        """If RPC returns value=null the row should be silently skipped."""
        job_id = "test_helius_null"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        null_resp = {
            "jsonrpc": "2.0",
            "result": {
                "context": {"slot": 100},
                "value": None,
            },
            "id": 1,
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = null_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "FakePoolAddr111", 60, 1, str(tmp_path), "fake_api_key"
            )

        assert _fetch_jobs[job_id]["status"] == "completed"
        assert _fetch_jobs[job_id]["rows"] == 0
        assert list(tmp_path.glob("raydium_*.parquet")) == []

    @pytest.mark.asyncio
    async def test_http_error_marks_job_error(self, tmp_path) -> None:
        job_id = "test_helius_error"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "FakePoolAddr111", 60, 1, str(tmp_path), "fake_api_key"
            )

        assert _fetch_jobs[job_id]["status"] == "error"
        assert "Connection refused" in _fetch_jobs[job_id]["error"]

    @pytest.mark.asyncio
    async def test_total_fetches_calculation(self, tmp_path) -> None:
        """interval=60s, duration=5min → total_fetches = 5."""
        job_id = "test_helius_total_fetches"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        helius_resp = _build_helius_response(1_000_000_000_000, 148_000_000_000)

        call_count = 0

        async def fake_post(url, json=None, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = helius_resp
            return mock_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = fake_post

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # interval=60s, duration=5min → (5*60)//60 = 5 fetches
                await _run_helius_fetch(
                    job_id, "FakePoolAddr111", 60, 5, str(tmp_path), "fake_api_key"
                )

        assert call_count == 5
        assert _fetch_jobs[job_id]["total"] == 5
        assert _fetch_jobs[job_id]["rows"] == 5

    @pytest.mark.asyncio
    async def test_slot_recorded_from_context(self, tmp_path) -> None:
        job_id = "test_helius_slot"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        helius_resp = _build_helius_response(1_000_000_000_000, 148_000_000_000, slot=999_888_777)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = helius_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "FakePoolAddr111", 60, 1, str(tmp_path), "fake_api_key"
            )

        df = pl.read_parquet(list(tmp_path.glob("raydium_*.parquet"))[0])
        assert df.row(0, named=True)["slot"] == 999_888_777

    @pytest.mark.asyncio
    async def test_dex_and_mints_are_hardcoded(self, tmp_path) -> None:
        job_id = "test_helius_dex"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        helius_resp = _build_helius_response(1_000_000_000_000, 148_000_000_000)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = helius_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "MyPool123", 60, 1, str(tmp_path), "fake_api_key"
            )

        df = pl.read_parquet(list(tmp_path.glob("raydium_*.parquet"))[0])
        row = df.row(0, named=True)
        assert row["dex"] == "raydium"
        assert row["pool_address"] == "MyPool123"
        assert row["base_mint"] == "So11111111111111111111111111111111111111112"
        assert row["quote_mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        assert row["fee_bps"] == 30


# ---------------------------------------------------------------------------
# 4. API endpoint integration tests
# ---------------------------------------------------------------------------

class TestDataAPIEndpoints:

    def test_fetch_binance_returns_job_id(self, client: TestClient) -> None:
        with patch("mev_kit.ui.routers.data.asyncio.create_task"):
            resp = client.post(
                "/api/data/fetch/binance",
                json={"symbol": "SOLUSDT", "interval": "1m", "days": 1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert "job_id" in data
        assert "binance_SOLUSDT" in data["job_id"]

    def test_fetch_historical_without_api_key_returns_error(self, client: TestClient) -> None:
        env = {k: v for k, v in os.environ.items() if k != "HELIUS_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            resp = client.post(
                "/api/data/fetch/historical",
                json={"pool_address": "FakePool", "interval": "5", "duration": "60"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "HELIUS_API_KEY" in data["error"]

    def test_fetch_historical_without_pool_address_returns_error(self, client: TestClient) -> None:
        with patch.dict(os.environ, {"HELIUS_API_KEY": "test_key"}):
            resp = client.post(
                "/api/data/fetch/historical",
                json={"interval": "5", "duration": "60"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "Pool address" in data["error"]

    def test_fetch_historical_with_valid_params_returns_job_id(self, client: TestClient) -> None:
        with patch.dict(os.environ, {"HELIUS_API_KEY": "test_key"}):
            with patch("mev_kit.ui.routers.data.asyncio.create_task"):
                resp = client.post(
                    "/api/data/fetch/historical",
                    json={"pool_address": "MyPool123", "interval": "5", "duration": "60"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert "job_id" in data

    def test_fetch_status_returns_job_dict(self, client: TestClient) -> None:
        # Seed a fake job directly into _fetch_jobs
        _fetch_jobs["fake_job_001"] = {"status": "running", "progress": 5}
        resp = client.get("/api/data/fetch/status")
        assert resp.status_code == 200
        status_data = resp.json()
        assert "fake_job_001" in status_data
        assert status_data["fake_job_001"]["status"] == "running"

    def test_download_file_returns_content(self, tmp_path, client: TestClient) -> None:
        # Write a small parquet to the temp dir used by client fixture
        from mev_kit.ui.server import create_app as _create_app
        app = _create_app(config_dir="config/", data_dir=str(tmp_path))
        tc = TestClient(app)

        df = pl.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        df.write_parquet(str(tmp_path / "test_download.parquet"))

        resp = tc.get("/api/data/files/test_download.parquet/download")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="test_download.parquet"'
        assert len(resp.content) > 0

    def test_download_nonexistent_returns_error(self, tmp_path) -> None:
        from mev_kit.ui.server import create_app as _create_app
        app = _create_app(config_dir="config/", data_dir=str(tmp_path))
        tc = TestClient(app)

        resp = tc.get("/api/data/files/does_not_exist.parquet/download")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_list_files_empty_returns_list(self, client: TestClient) -> None:
        resp = client.get("/api/data/files")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_delete_file_via_api(self, tmp_path) -> None:
        from mev_kit.ui.server import create_app as _create_app
        app = _create_app(config_dir="config/", data_dir=str(tmp_path))
        tc = TestClient(app)

        df = pl.DataFrame({"x": [1]})
        df.write_parquet(str(tmp_path / "to_delete.parquet"))

        resp = tc.delete("/api/data/files/to_delete.parquet")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert not (tmp_path / "to_delete.parquet").exists()

    def test_preview_file_via_api(self, tmp_path) -> None:
        from mev_kit.ui.server import create_app as _create_app
        app = _create_app(config_dir="config/", data_dir=str(tmp_path))
        tc = TestClient(app)

        df = pl.DataFrame({"col1": list(range(20)), "col2": [float(i) for i in range(20)]})
        df.write_parquet(str(tmp_path / "preview_test.parquet"))

        resp = tc.get("/api/data/files/preview_test.parquet/preview?limit=5")
        assert resp.status_code == 200
        preview = resp.json()
        assert len(preview["rows"]) == 5
        assert preview["total_rows"] == 20
        assert "col1" in preview["columns"]


# ---------------------------------------------------------------------------
# 5. End-to-end data pipeline test
# ---------------------------------------------------------------------------

class TestEndToEndDataPipeline:

    @pytest.mark.asyncio
    async def test_binance_fetch_to_parquet_to_preview_to_delete(self, tmp_path) -> None:
        """Full pipeline: mock Binance fetch → Parquet created → preview via API → delete via API."""
        # --- Step 1: run the fetch ---
        job_id = "e2e_binance"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0, "total": 0}

        candles = [list(MOCK_KLINE) for _ in range(12)]
        for i, c in enumerate(candles):
            c[0] = 1700000000000 + i * 60_000

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = candles

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_binance_fetch(job_id, "SOLUSDT", "1m", 1, str(tmp_path), use_us=False)

        assert _fetch_jobs[job_id]["status"] == "completed"
        filename = _fetch_jobs[job_id]["file"]

        # --- Step 2: verify Parquet schema with polars ---
        parquet_path = tmp_path / filename
        assert parquet_path.exists()
        df = pl.read_parquet(parquet_path)
        assert df.shape[0] == 12
        for col in ("symbol", "price", "volume", "timestamp", "open", "high", "low", "close"):
            assert col in df.columns
        # timestamp column should be datetime type
        assert df["timestamp"].dtype in (pl.Datetime, pl.Datetime("us"), pl.Datetime("us", "UTC"),
                                          pl.Datetime("ns"), pl.Datetime("ns", "UTC"))

        # --- Step 3: preview via TestClient ---
        from mev_kit.ui.server import create_app as _create_app
        app = _create_app(config_dir="config/", data_dir=str(tmp_path))
        tc = TestClient(app)

        resp = tc.get(f"/api/data/files/{filename}/preview?limit=5")
        assert resp.status_code == 200
        preview = resp.json()
        assert preview["total_rows"] == 12
        assert len(preview["rows"]) == 5

        # --- Step 4: delete via API ---
        resp = tc.delete(f"/api/data/files/{filename}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert not parquet_path.exists()

    @pytest.mark.asyncio
    async def test_helius_fetch_to_parquet_schema(self, tmp_path) -> None:
        """Helius fetch produces a Parquet with the expected schema."""
        job_id = "e2e_helius"
        _fetch_jobs[job_id] = {"status": "running", "progress": 0}

        helius_resp = _build_helius_response(
            base_lamports=2_000_000_000_000,  # 2000 SOL
            quote_micro=300_000_000_000,       # 300000 USDC → price = 150
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = helius_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("mev_kit.ui.routers.data.httpx.AsyncClient", return_value=mock_client):
            await _run_helius_fetch(
                job_id, "SomePoolXYZ", 60, 1, str(tmp_path), "fake_key"
            )

        parquet_files = list(tmp_path.glob("raydium_*.parquet"))
        assert len(parquet_files) == 1
        df = pl.read_parquet(parquet_files[0])

        assert df.shape[0] == 1
        row = df.row(0, named=True)
        assert row["price"] == pytest.approx(150.0)
        assert row["base_reserve"] == pytest.approx(2000.0)
        assert row["quote_reserve"] == pytest.approx(300000.0)

        # Verify column types
        schema = df.schema
        assert schema["base_reserve"] == pl.Float64
        assert schema["quote_reserve"] == pl.Float64
        assert schema["price"] == pl.Float64
        assert schema["fee_bps"] in (pl.Int32, pl.Int64)
        assert schema["slot"] in (pl.Int32, pl.Int64)
