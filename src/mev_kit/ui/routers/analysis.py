"""Results analysis endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/{db_name}")
async def get_summary(request: Request, db_name: str) -> dict[str, Any]:
    db_path = Path(request.app.state.data_dir) / db_name
    if not db_path.exists():
        return {"error": f"Database not found: {db_name}"}

    async with aiosqlite.connect(str(db_path)) as db:
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
    db_path = Path(request.app.state.data_dir) / db_name
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
