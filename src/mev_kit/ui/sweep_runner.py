"""Parameter sweep engine — grid search across strategy parameters.

Runs multiple backtests with different parameter combinations and
ranks results by risk-adjusted metrics.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from mev_kit.ui.backtest_runner import BacktestRunner

logger = structlog.get_logger()

SWEEP_DB = "./data/sweep_results.db"


class SweepRunner:
    """Runs a grid search across strategy parameters."""

    def __init__(self) -> None:
        self._state: str = "idle"
        self._results: list[dict] = []
        self._progress: int = 0
        self._total: int = 0
        self._current_params: dict = {}

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self._state,
            "progress": self._progress,
            "total": self._total,
        }
        if self._state == "running":
            result["current_params"] = self._current_params
        if self._state in ("completed", "error"):
            result["results"] = self._results
        return result

    async def run(
        self,
        data_path: str,
        strategy: str,
        sweep_params: dict[str, list],
        base_config: dict,
        _internal: bool = False,
    ) -> None:
        """Run grid search across all parameter combinations."""
        if not _internal and self._state == "running":
            raise RuntimeError("Sweep already running")

        self._state = "running"
        self._results = []
        self._progress = 0

        # Generate all combinations
        param_names = list(sweep_params.keys())
        param_values = list(sweep_params.values())
        combinations = list(itertools.product(*param_values))
        self._total = len(combinations)

        try:
            for i, combo in enumerate(combinations):
                params = dict(zip(param_names, combo))
                self._current_params = params
                self._progress = i

                # Build config for this run
                config = {**base_config, **params, "strategy": strategy}

                # Run a single backtest
                runner = BacktestRunner()
                try:
                    await runner.run(data_path=data_path, config=config)
                    status = runner.status()
                    r = status.get("results", {})
                    risk = r.get("risk_metrics", {})

                    self._results.append({
                        "params": params,
                        "total_trades": r.get("total_trades", 0),
                        "total_profit_sol": r.get("total_profit_sol", 0),
                        "win_rate": r.get("win_rate", 0),
                        "sharpe_ratio": risk.get("sharpe_ratio", 0),
                        "max_drawdown_sol": risk.get("max_drawdown_sol", 0),
                        "profit_factor": risk.get("profit_factor", 0),
                        "avg_spread_bps": r.get("avg_spread_bps", 0),
                    })
                except Exception as exc:
                    self._results.append({
                        "params": params,
                        "error": str(exc),
                        "total_trades": 0,
                        "sharpe_ratio": 0,
                    })

            # Sort by Sharpe ratio (best first)
            self._results.sort(key=lambda x: x.get("sharpe_ratio", 0), reverse=True)
            self._progress = self._total
            self._state = "completed"

            # Persist sweep results
            await self._persist_sweep(data_path, strategy, sweep_params)

        except Exception as exc:
            self._state = "error"
            logger.warning("sweep_runner.error", error=str(exc))

    async def _persist_sweep(
        self, data_path: str, strategy: str, sweep_params: dict
    ) -> None:
        """Save sweep results to SQLite."""
        try:
            Path(SWEEP_DB).parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(SWEEP_DB) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS sweeps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        data_file TEXT NOT NULL,
                        sweep_params TEXT NOT NULL,
                        results TEXT NOT NULL,
                        best_sharpe REAL,
                        best_params TEXT
                    )
                """)
                best = self._results[0] if self._results else {}
                await db.execute(
                    "INSERT INTO sweeps (timestamp, strategy, data_file, sweep_params, results, best_sharpe, best_params) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(UTC).isoformat(),
                        strategy,
                        data_path,
                        json.dumps(sweep_params),
                        json.dumps(self._results),
                        best.get("sharpe_ratio", 0),
                        json.dumps(best.get("params", {})),
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("sweep_runner.persist_failed", error=str(exc))

    async def run_walk_forward(
        self,
        data_path: str,
        strategy: str,
        sweep_params: dict[str, list],
        base_config: dict,
        train_pct: float = 0.7,
    ) -> None:
        """Walk-forward validation: optimize on training data, validate on test data.

        1. Split dataset at train_pct (default 70/30)
        2. Run parameter sweep on training portion
        3. Take best params, run single backtest on test portion
        4. Compare in-sample vs out-of-sample metrics
        """
        import polars as pl

        self._state = "running"
        self._results = []
        self._progress = 0

        try:
            # Load and split data
            df = pl.read_parquet(data_path)
            split_idx = int(len(df) * train_pct)

            # Write train/test splits to temp files
            train_path = data_path.replace(".parquet", "_train.parquet")
            test_path = data_path.replace(".parquet", "_test.parquet")
            df[:split_idx].write_parquet(train_path)
            df[split_idx:].write_parquet(test_path)

            # Phase 1: Sweep on training data
            self._total = len(list(itertools.product(*sweep_params.values()))) + 1
            await self.run(
                data_path=train_path,
                strategy=strategy,
                sweep_params=sweep_params,
                base_config=base_config,
                _internal=True,
            )

            train_results = list(self._results)
            best_params = train_results[0]["params"] if train_results else {}

            # Phase 2: Validate best params on test data
            self._state = "running"
            self._current_params = {"phase": "validation", **best_params}

            runner = BacktestRunner()
            config = {**base_config, **best_params, "strategy": strategy}
            await runner.run(data_path=test_path, config=config)
            test_status = runner.status()
            test_r = test_status.get("results", {})
            test_risk = test_r.get("risk_metrics", {})

            # Compile walk-forward results
            train_best = train_results[0] if train_results else {}

            self._results = [{
                "type": "walk_forward",
                "train_results": train_results[:10],  # Top 10 from sweep
                "best_params": best_params,
                "in_sample": {
                    "trades": train_best.get("total_trades", 0),
                    "profit_sol": train_best.get("total_profit_sol", 0),
                    "sharpe": train_best.get("sharpe_ratio", 0),
                    "drawdown": train_best.get("max_drawdown_sol", 0),
                },
                "out_of_sample": {
                    "trades": test_r.get("total_trades", 0),
                    "profit_sol": test_r.get("total_profit_sol", 0),
                    "sharpe": test_risk.get("sharpe_ratio", 0),
                    "drawdown": test_risk.get("max_drawdown_sol", 0),
                },
                "overfit_warning": (
                    train_best.get("sharpe_ratio", 0) > 2 * test_risk.get("sharpe_ratio", 0.001)
                    if test_risk.get("sharpe_ratio", 0) > 0
                    else False
                ),
                "train_pct": train_pct,
                "train_rows": split_idx,
                "test_rows": len(df) - split_idx,
            }]

            self._state = "completed"
            self._progress = self._total

            # Clean up temp files
            for f in [train_path, test_path]:
                try:
                    os.unlink(f)
                except OSError:
                    pass

        except Exception as exc:
            self._state = "error"
            logger.warning("sweep_runner.walk_forward_error", error=str(exc))
