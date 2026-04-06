"""Risk metrics for strategy evaluation.

Computes equity curve, drawdown, and risk-adjusted return metrics
from a sequence of trade P&Ls.
"""

from __future__ import annotations
from typing import Any


def compute_equity_curve(trades: list[dict]) -> list[dict]:
    """Build mark-to-market equity curve from trade results.

    Returns list of {timestamp, cumulative_pnl, drawdown, high_water_mark}
    """
    curve = []
    cumulative = 0.0
    high_water = 0.0

    for trade in trades:
        pnl = trade.get("simulated_profit_sol", 0) or trade.get("estimated_profit_sol", 0)
        cumulative += pnl
        high_water = max(high_water, cumulative)
        drawdown = cumulative - high_water  # negative when underwater

        curve.append({
            "timestamp": trade.get("detected_at") or trade.get("timestamp", ""),
            "pnl": round(cumulative, 8),
            "drawdown": round(drawdown, 8),
            "high_water": round(high_water, 8),
        })

    return curve


def compute_risk_metrics(trades: list[dict]) -> dict[str, Any]:
    """Compute risk-adjusted performance metrics.

    Returns: sharpe, sortino, calmar, profit_factor, max_drawdown,
    max_drawdown_duration, avg_win, avg_loss, win_streak, loss_streak
    """
    if not trades:
        return _empty_metrics()

    pnls = [t.get("simulated_profit_sol", 0) or t.get("estimated_profit_sol", 0) for t in trades]

    if len(pnls) < 2:
        return _empty_metrics()

    import math

    # Basic stats
    mean_pnl = sum(pnls) / len(pnls)
    variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
    std_pnl = math.sqrt(variance) if variance > 0 else 0.001

    # Sharpe ratio (annualized) — derive dataset duration from timestamps
    timestamps = [t.get("detected_at") or t.get("timestamp", "") for t in trades]
    valid_ts = sorted([ts for ts in timestamps if ts])
    if len(valid_ts) >= 2:
        try:
            from datetime import datetime as _dt
            first = _dt.fromisoformat(str(valid_ts[0]).replace("Z", "+00:00"))
            last = _dt.fromisoformat(str(valid_ts[-1]).replace("Z", "+00:00"))
            total_days = max(1, (last - first).total_seconds() / 86400)
        except (ValueError, TypeError):
            total_days = 7  # fallback
    else:
        total_days = 7  # fallback
    trades_per_day = len(pnls) / total_days
    annualization = math.sqrt(max(1, trades_per_day * 365))
    sharpe = (mean_pnl / std_pnl) * annualization if std_pnl > 0 else 0

    # Sortino ratio (downside deviation only)
    downside_pnls = [p for p in pnls if p < 0]
    if downside_pnls:
        downside_var = sum(p ** 2 for p in downside_pnls) / len(downside_pnls)
        downside_std = math.sqrt(downside_var)
        sortino = (mean_pnl / downside_std) * annualization if downside_std > 0 else 0
    else:
        sortino = float('inf') if mean_pnl > 0 else 0

    # Max drawdown
    cumulative = 0.0
    high_water = 0.0
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_start = 0

    for i, p in enumerate(pnls):
        cumulative += p
        if cumulative > high_water:
            high_water = cumulative
            if current_dd_start > 0:
                max_dd_duration = max(max_dd_duration, i - current_dd_start)
            current_dd_start = i
        dd = high_water - cumulative
        if dd > max_dd:
            max_dd = dd

    # Calmar ratio (return / max drawdown)
    total_return = sum(pnls)
    calmar = total_return / max_dd if max_dd > 0 else (float('inf') if total_return > 0 else 0)

    # Profit factor (gross profit / gross loss)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)

    # Win/loss stats
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    # Streaks
    max_win_streak = 0
    max_loss_streak = 0
    current_streak = 0
    for p in pnls:
        if p > 0:
            current_streak = current_streak + 1 if current_streak > 0 else 1
            max_win_streak = max(max_win_streak, current_streak)
        elif p < 0:
            current_streak = current_streak - 1 if current_streak < 0 else -1
            max_loss_streak = max(max_loss_streak, abs(current_streak))
        else:
            current_streak = 0

    return {
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(min(sortino, 999), 2),  # cap inf display
        "calmar_ratio": round(min(calmar, 999), 2),
        "profit_factor": round(min(profit_factor, 999), 2),
        "max_drawdown_sol": round(max_dd, 6),
        "max_drawdown_duration": max_dd_duration,
        "avg_win_sol": round(avg_win, 6),
        "avg_loss_sol": round(avg_loss, 6),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "gross_profit_sol": round(gross_profit, 6),
        "gross_loss_sol": round(gross_loss, 6),
    }


def compute_hourly_breakdown(trades: list[dict]) -> list[dict]:
    """Break down P&L by hour of day (UTC).

    Returns list of 24 dicts: {hour, trade_count, total_pnl, win_rate}
    """
    hours: dict[int, dict] = {h: {"count": 0, "pnl": 0.0, "wins": 0} for h in range(24)}

    for t in trades:
        ts = t.get("detected_at") or t.get("timestamp", "")
        try:
            if isinstance(ts, str) and len(ts) >= 13:
                hour = int(ts[11:13])
            else:
                hour = 0
        except (ValueError, IndexError):
            hour = 0

        pnl = t.get("simulated_profit_sol", 0) or t.get("estimated_profit_sol", 0)
        hours[hour]["count"] += 1
        hours[hour]["pnl"] += pnl
        if pnl > 0:
            hours[hour]["wins"] += 1

    return [
        {
            "hour": h,
            "trade_count": d["count"],
            "total_pnl": round(d["pnl"], 6),
            "win_rate": round(d["wins"] / d["count"], 3) if d["count"] > 0 else 0,
        }
        for h, d in sorted(hours.items())
    ]


def _empty_metrics() -> dict[str, Any]:
    return {
        "sharpe_ratio": 0, "sortino_ratio": 0, "calmar_ratio": 0,
        "profit_factor": 0, "max_drawdown_sol": 0, "max_drawdown_duration": 0,
        "avg_win_sol": 0, "avg_loss_sol": 0, "max_win_streak": 0,
        "max_loss_streak": 0, "gross_profit_sol": 0, "gross_loss_sol": 0,
    }
