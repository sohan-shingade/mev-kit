"""Results analysis endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/databases")
async def list_databases(request: Request) -> list[dict[str, str]]:
    """Discover all .db files in the data directory.

    Returns a list of objects with 'name' (filename) and 'path' (relative)
    for the frontend DB selector.
    """
    data_dir = Path(request.app.state.data_dir)
    if not data_dir.exists():
        return []
    dbs = []
    for db_file in sorted(data_dir.glob("*.db")):
        dbs.append({"name": db_file.stem, "file": db_file.name})
    return dbs


@router.get("/{db_name}")
async def get_summary(request: Request, db_name: str) -> dict[str, Any]:
    db_path = _resolve_db_path(request, db_name)
    if not db_path.exists():
        return {"error": f"Database not found: {db_name}"}

    async with aiosqlite.connect(str(db_path)) as db:
        # Check that the table exists before querying
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
        ) as cur:
            if await cur.fetchone() is None:
                return {"error": f"No paper_trades table in {db_name}"}

        async with db.execute("SELECT COUNT(*) FROM paper_trades") as cur:
            total = (await cur.fetchone())[0]

        if total == 0:
            return {"total_trades": 0}

        async with db.execute("""
            SELECT
                SUM(simulated_profit_sol), AVG(simulated_profit_sol),
                MAX(simulated_profit_sol), MIN(simulated_profit_sol),
                AVG(spread_bps), MIN(timestamp), MAX(timestamp),
                SUM(CASE WHEN simulated_profit_sol > 0 THEN 1 ELSE 0 END)
            FROM paper_trades
        """) as cur:
            row = await cur.fetchone()

    return {
        "total_trades": total,
        "total_profit_sol": round(row[0] or 0, 6),
        "avg_profit_sol": round(row[1] or 0, 6),
        "best_trade_sol": round(row[2] or 0, 6),
        "worst_trade_sol": round(row[3] or 0, 6),
        "avg_spread_bps": round(row[4] or 0, 1),
        "first_trade": row[5],
        "last_trade": row[6],
        "win_rate": round((row[7] or 0) / max(1, total), 4),
    }


@router.get("/{db_name}/trades")
async def get_trades(
    request: Request,
    db_name: str,
    page: int = 1,
    per_page: int = 50,
    sort: str = "timestamp",
    direction: str | None = None,
) -> dict[str, Any]:
    db_path = _resolve_db_path(request, db_name)
    if not db_path.exists():
        return {"error": f"Database not found: {db_name}"}

    offset = (page - 1) * per_page
    where = ""
    params: list = []
    if direction:
        where = "WHERE direction = ?"
        params.append(direction)

    allowed_sorts = {"timestamp", "spread_bps", "simulated_profit_sol", "dex_price"}
    sort_col = sort if sort in allowed_sorts else "timestamp"

    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(f"SELECT COUNT(*) FROM paper_trades {where}", params) as cur:
            total = (await cur.fetchone())[0]

        query = f"SELECT * FROM paper_trades {where} ORDER BY {sort_col} DESC LIMIT ? OFFSET ?"
        async with db.execute(query, [*params, per_page, offset]) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return {
        "trades": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def _resolve_db_path(request: Request, db_name: str) -> Path:
    """Resolve a db_name to a file path in the data directory.

    Accepts both bare names (e.g. 'backtest_results') and names
    with the .db extension (e.g. 'backtest_results.db').
    """
    data_dir = Path(request.app.state.data_dir)
    if db_name.endswith(".db"):
        return data_dir / db_name
    return data_dir / db_name
