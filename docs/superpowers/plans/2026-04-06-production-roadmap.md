# mev-kit Production Roadmap

**Goal:** Take mev-kit from "research prototype" to "a quant desk trusts this with capital allocation decisions."

**Derived from:** Quant desk workflow simulation (2026-04-06), fill pipeline report, UX audit, 184 passing tests, 60+ commits of development.

**Current state:** Strong architecture, excellent data pipeline, working UI. Backtest P&L numbers are 2-10x inflated due to fill simulation gaps. Critical pipeline bugs block reliable iteration.

---

## Sprint 1: Fix Critical Bugs (3 days)

Everything else depends on a reliable pipeline. Fix these first.

### 1.1 Pipeline runner: call before()/after() lifecycle hooks

**Bug:** The Detector base class declares `before()` and `after()` hooks. The documentation describes them. Example strategies use them. But `pipeline/runner.py` never calls them.

**File:** `src/mev_kit/pipeline/runner.py` lines 155-180

**Fix:** In `_process_loop()`, call `detector.before(update)` before `detector.process(update)`, and `detector.after(update, opportunities)` after.

**Test:** Verify `statistical_arb` detector's `before()` hook actually tracks spread history.

### 1.2 BacktestRunner: cancel orphaned tasks on stop/restart

**Bug:** When a backtest is stopped or a new one starts, the old `pipeline.run()` asyncio task is never cancelled. It continues running in the background, consuming CPU and potentially corrupting state.

**File:** `src/mev_kit/ui/backtest_runner.py`

**Fix:** In `run()`, before starting a new pipeline, cancel and await the old task:
```python
if self._task and not self._task.done():
    self._task.cancel()
    try:
        await self._task
    except asyncio.CancelledError:
        pass
```

**Test:** Start backtest, stop it, start another. Verify no orphaned tasks.

### 1.3 MergedReplayAdapter: fix CEX yield indentation

**Bug:** The CEX `yield` statement in `merged_replay.py` is at the wrong indentation level, causing it to execute outside the `if emit_cex:` guard.

**File:** `src/mev_kit/adapters/ingest/merged_replay.py`

**Fix:** Verify the yield is inside the `if emit_cex:` block.

**Test:** Run backtest with `use_sources=["dex"]` only. Verify zero CEX updates are emitted.

### 1.4 Backtest hang on high trade counts

**Bug:** Backtests with 5000+ trades hang during result persistence to SQLite.

**File:** `src/mev_kit/ui/backtest_runner.py`, `_persist_results_to_sqlite()`

**Root cause investigation:** Likely the SQLite inserts are done one-by-one with individual commits. For 5000+ rows, this is slow enough to block the event loop.

**Fix:** Batch inserts with `executemany()` and a single commit. Add a timeout to the persistence step.

### 1.5 Nonexistent strategy: raise instead of silent fallback

**Bug:** Already partially fixed (raises ValueError) but the error message doesn't surface clearly in the UI.

**Fix:** Ensure the backtest error state shows the ValueError message in the results panel.

**Sprint 1 deliverable:** All 184+ tests pass, pipeline lifecycle is correct, backtests complete reliably for any trade count.

---

## Sprint 2: Honest Fill Pipeline (5 days)

Make the backtest P&L numbers trustworthy. After this sprint, a quant should be able to look at backtest results and make a go/no-go decision with reasonable confidence.

### 2.1 Volume-weighted pool depth (1 day)

**Problem:** Pool depth is hardcoded (50K SOL for Raydium). Real pools range 1K-500K.

**Fix:** Use the candle's `volume` column as a liquidity proxy.

```python
def estimate_pool_depth(candle_volume_sol: float, interval_minutes: int = 1) -> float:
    """Estimate pool depth from candle volume.
    
    Empirical relationship: pool depth ≈ 5% of daily volume
    (based on Raydium SOL/USDC historical data)
    """
    daily_volume = candle_volume_sol * (1440 / interval_minutes)
    return max(1000, daily_volume * 0.05)  # Floor at 1K SOL
```

**Where:** `src/mev_kit/adapters/simulators/fill_simulator.py`

**Impact:** Fixes 10-100x slippage errors for non-SOL/USDC pairs.

**Data needed:** The merged Parquet already has a `volume` column from Binance/Birdeye data. Pass it through the Opportunity metadata.

### 2.2 Two-leg execution model (2 days)

**Problem:** CEX-DEX arb requires TWO trades but the fill simulator only models one leg. Profit is inflated 2x.

**Fix:** For arb strategies (detected via `needs_dual_source`), simulate both legs:

```python
# Leg 1: DEX execution (buy cheap on-chain)
dex_result = self._simulate_dex_leg(opportunity, trade_size)

# Leg 2: CEX execution (sell expensive on CEX)  
cex_result = self._simulate_cex_leg(opportunity, trade_size)

# Net profit = CEX output - DEX cost - fees_both - tip
net = cex_result.output - dex_result.cost - dex_result.fee - cex_result.fee - tip
```

**Where:** New method in `FillSimulator`. The venue selector becomes a pair: `(dex_venue, cex_venue)`.

**UI change:** Backtest form shows "DEX Venue" + "CEX Venue" dropdowns for arb strategies.

### 2.3 Dynamic landing rate (1 day)

**Problem:** Static 40% landing rate is wrong for every pair.

**Fix:** Model landing rate as a function of competition intensity:

```python
def dynamic_landing_rate(
    opportunities_in_window: int,  # How many opps detected in last N minutes
    profit_bps: int,               # How attractive this opp is
    hour_utc: int,                 # Time of day
) -> float:
    # More opportunities = more competition = lower landing
    competition = min(1.0, 50 / max(1, opportunities_in_window))
    
    # Peak hours (14-22 UTC) = more searchers
    time_factor = 0.7 if 14 <= hour_utc <= 22 else 0.9
    
    # Larger profits attract more competition
    profit_factor = max(0.3, 1.0 - profit_bps / 200)
    
    return min(0.95, competition * time_factor * profit_factor)
```

**Where:** `FillSimulator._check_landing()` — replace static rate with dynamic calculation.

**Data needed:** Track opportunity count per hour within the simulator (already have `_total_simulated`).

### 2.4 Execution cost breakdown (1 day)

**Problem:** Users can't see where their profit goes.

**Fix:** Add per-trade cost breakdown to the SimulationResult and display in the trade table.

```python
# New fields in SimulationResult or Opportunity metadata
cost_breakdown = {
    "venue_fee_bps": 25,
    "slippage_bps": 3.2,
    "tip_bps": 8.0,
    "staleness_bps": 1.5,
    "gas_lamports": 5000,
    "total_cost_bps": 37.7,
    "gross_spread_bps": 45.0,
    "net_profit_bps": 7.3,
}
```

**UI:** Add expandable cost breakdown row in the trade table. Add a pie chart in results showing fee/slippage/tip/net split.

### 2.5 Survivorship bias warnings (0.5 day)

**Problem:** Strategies with 100% win rate look amazing but are simulation artifacts.

**Fix:** After backtest completion, run sanity checks:

```python
warnings = []
if win_rate > 0.90:
    warnings.append("Win rate >90% is unusually high — may indicate simulation bias")
if avg_spread < 5:
    warnings.append("Average spread <5 bps is below typical execution costs")  
if total_trades / total_updates > 0.3:
    warnings.append("Detection rate >30% suggests overly aggressive parameters")
if max_drawdown == 0:
    warnings.append("Zero drawdown is unrealistic — check fill simulation settings")
```

**UI:** Show warnings in an amber panel below the results summary cards.

**Sprint 2 deliverable:** Backtest P&L is within 2x of real execution (down from 10x). Cost breakdown visible per trade. Bias warnings catch obvious issues.

---

## Sprint 3: Risk Analytics (5 days)

A quant can't evaluate a strategy without risk metrics. This sprint adds the analytics layer.

### 3.1 Mark-to-market equity curve (2 days)

**What:** Track cumulative P&L over time, not just total. Calculate max drawdown, drawdown duration, underwater periods.

**Implementation:**
- In BacktestRunner, build an equity curve array: `[(timestamp, cumulative_pnl), ...]`
- Calculate: max drawdown, max drawdown duration, recovery time, underwater percentage
- Return in results alongside existing metrics

**UI:** Replace the simple PnlChart (which only shows opportunities) with a proper equity curve. Add drawdown visualization as a filled area below the curve.

### 3.2 Risk-adjusted metrics (1 day)

**What:** Sharpe ratio, Sortino ratio, Calmar ratio, profit factor.

**Implementation:**
```python
def compute_risk_metrics(equity_curve: list[float], risk_free_rate: float = 0.05) -> dict:
    returns = [equity_curve[i] - equity_curve[i-1] for i in range(1, len(equity_curve))]
    
    sharpe = (mean(returns) - risk_free_rate/252) / std(returns) * sqrt(252)
    
    downside_returns = [r for r in returns if r < 0]
    sortino = (mean(returns) - risk_free_rate/252) / std(downside_returns) * sqrt(252)
    
    max_dd = max_drawdown(equity_curve)
    calmar = (sum(returns) / len(returns) * 252) / abs(max_dd) if max_dd != 0 else 0
    
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    return {
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_sol": round(max_dd, 6),
        "max_drawdown_pct": round(max_dd / max(equity_curve) * 100, 1),
    }
```

**UI:** Add risk metrics as additional summary cards below the existing ones. Color-code: Sharpe >1 green, 0-1 amber, <0 red.

### 3.3 Time-of-day analysis (1 day)

**What:** P&L, trade count, and win rate broken down by hour of day.

**Implementation:** Group trades by `hour(timestamp)`, compute per-hour metrics.

**UI:** Heatmap chart (24 columns, color = P&L intensity). Table below with hourly breakdown.

### 3.4 Slippage distribution chart (0.5 day)

**What:** Histogram of realized slippage per trade.

**UI:** Bar chart with buckets (0-1 bps, 1-5 bps, 5-10 bps, 10-25 bps, 25+ bps). Show mean, median, p95, p99.

### 3.5 Fee breakdown visualization (0.5 day)

**What:** Where does gross profit go?

**UI:** Pie/donut chart showing: Net profit retained, Venue fees, Slippage, Tips, Gas. Show percentage labels.

**Sprint 3 deliverable:** A quant can look at backtest results and answer: "Is this strategy's risk/reward acceptable?" with Sharpe, drawdown, and time analysis.

---

## Sprint 4: Strategy Optimization (7 days)

The most requested feature from the workflow simulation: automated parameter sweeps.

### 4.1 Parameter sweep engine (3 days)

**What:** Run backtests across a grid of parameter values. Use the `hyperparameters()` method on detectors.

**Implementation:**
- New endpoint: `POST /api/backtest/sweep`
- Accepts: data_file, strategy, param_ranges (dict of param → [values])
- Runs backtests for all combinations (grid search)
- Returns: table of (params → results) sorted by Sharpe ratio

**Example:**
```json
{
  "data_file": "merged.parquet",
  "strategy": "cex_dex_arb",
  "sweep": {
    "min_spread_bps": [3, 5, 10, 15, 20],
    "fee_bps": [5, 10, 15, 25],
    "position_size_sol": [0.1, 0.5, 1.0]
  }
}
// Runs 5 × 4 × 3 = 60 backtests
```

**UI:** New "Sweep" tab on the Backtest page. Heatmap visualization of Sharpe ratio across parameter pairs.

### 4.2 Walk-forward validation (3 days)

**What:** Split data into training and testing periods. Optimize on training, validate on test.

**Implementation:**
- Split dataset at configurable ratio (default: 70/30)
- Run parameter sweep on training data
- Take best params, run single backtest on test data
- Report both in-sample and out-of-sample metrics
- Flag overfitting: if in-sample Sharpe > 2x out-of-sample Sharpe

**UI:** Results show side-by-side: "In-Sample" vs "Out-of-Sample" metrics with delta highlighting.

### 4.3 Result versioning and comparison (1 day)

**What:** Save every backtest run with its params, strategy, data file, and results. Compare any two runs side-by-side.

**Implementation:**
- SQLite table: `backtest_runs` with columns: id, timestamp, strategy, data_file, params_json, results_json, metrics_json
- API: `GET /api/backtest/history`, `GET /api/backtest/compare?run_a=X&run_b=Y`

**UI:** "History" panel shows all past runs. Click two to compare. Delta highlighting on metrics.

**Sprint 4 deliverable:** A quant can run 60 parameter combinations, find the best, validate it out-of-sample, and compare against previous strategies — all from the UI.

---

## Sprint 5: Multi-Asset & Advanced Features (5 days)

### 5.1 Multi-asset backtesting (2 days)

**What:** Run the same strategy across SOL/USDC, WIF/USDC, JUP/USDC simultaneously.

**Implementation:** The pipeline already supports multiple adapters. Extend BacktestRunner to accept multiple data files and create one adapter per file. The detector processes all updates and can emit opportunities for any pair.

### 5.2 Live execution bridge (2 days)

**What:** One-click transition from backtest to paper trading with the same strategy and params.

**Implementation:** "Go Paper" button on backtest results that:
1. Saves the strategy + params as a config profile
2. Switches to Dashboard
3. Starts paper pipeline with those settings
4. Shows backtest results alongside live results for comparison

### 5.3 Alerting (1 day)

**What:** Notifications when pipeline state changes (circuit breaker tripped, large P&L event, connection lost).

**Implementation:** WebSocket push to UI for alerts. Optional webhook URL in config for external notifications (Slack, Discord, PagerDuty).

---

## Sprint 6: Production Hardening (3 days)

### 6.1 Comprehensive test coverage (1 day)

- Test the fill simulator with known inputs and verify outputs match on-chain math
- Test the data merge pipeline with edge cases (different timezones, missing rows, duplicate timestamps)
- Test the pipeline lifecycle (start, stop, restart, concurrent access)
- Target: 95%+ coverage on core modules

### 6.2 Performance optimization (1 day)

- Profile the backtest pipeline for 10K+ trade datasets
- Optimize SQLite persistence (batch inserts, WAL mode)
- Add data caching for repeated backtests on same dataset
- Lazy-load heavy UI components (Monaco editor, charts)

### 6.3 Error handling audit (1 day)

- Every API endpoint returns structured errors, never 500s
- Every background task has a timeout and error propagation
- The UI shows every error with context and suggested fix
- No "running forever" states — everything has a maximum lifetime

---

## Timeline Summary

| Sprint | Duration | Deliverable |
|--------|----------|-------------|
| **1: Critical Bugs** | 3 days | Reliable pipeline, all tests pass |
| **2: Honest Fills** | 5 days | P&L within 2x of reality, cost breakdown |
| **3: Risk Analytics** | 5 days | Sharpe, drawdown, time analysis |
| **4: Optimization** | 7 days | Parameter sweep, walk-forward, versioning |
| **5: Advanced** | 5 days | Multi-asset, live bridge, alerts |
| **6: Hardening** | 3 days | Tests, performance, error handling |
| **Total** | **28 days** | Production-ready for capital allocation |

## Definition of "Production Ready"

A quant desk can:
1. ✅ Fetch multi-venue historical data for any Solana token pair
2. ✅ Write a custom detector with proper lifecycle hooks
3. ✅ Backtest with realistic fill simulation (within 2x of live P&L)
4. ✅ See risk-adjusted metrics (Sharpe, drawdown, profit factor)
5. ✅ Run parameter sweeps and validate out-of-sample
6. ✅ Compare strategies side-by-side with versioned results
7. ✅ Transition from backtest to paper trading with one click
8. ✅ Monitor live pipeline with error surfacing and alerts
9. ✅ Trust that the backtest won't hang, lose data, or show misleading numbers
