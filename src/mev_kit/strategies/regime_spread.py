"""Volatility Regime Spread Capture — adaptive CEX-DEX strategy.

A strategy that adapts its behavior based on the current volatility
regime of CEX-DEX spreads. Most MEV strategies use static thresholds.
This one switches between mean-reversion and momentum depending on
whether the market is calm or volatile.

The core insight: in low-volatility regimes, spreads mean-revert quickly
(fade them). In high-volatility regimes, spreads trend and blow out
(follow them). The regime transition is the signal.

WHY THIS WORKS ON FREE TIER:
- Professional searchers optimize for speed on static signals (CEX > DEX, arb)
- This strategy optimizes for ADAPTATION — the regime classification
  uses 30-60 minutes of history, not millisecond latency
- It targets mid-cap tokens (JTO, JUP, RAY) where competition is lower
- It can tolerate 1-5 second execution latency because the regime
  persists for minutes to hours, not milliseconds

Required data sources: Source.BINANCE_WS (CEX), Source.HELIUS_WS or
Source.PARQUET_REPLAY (DEX)

Author: mev-kit research
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from datetime import UTC, datetime
from enum import Enum

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class Regime(Enum):
    LOW_VOL = "low_vol"
    HIGH_VOL = "high_vol"
    TRANSITION = "transition"


class RegimeSpreadDetector(Detector):
    """Volatility Regime Spread Capture.

    Classifies the market into low-vol or high-vol regimes using
    rolling realized volatility of CEX-DEX spreads, then applies
    the appropriate trading rule:

    LOW_VOL regime (spread mean-reverts):
        Signal: spread deviates > entry_zscore standard deviations from mean
        Direction: FADE the spread (buy when cheap, sell when expensive)
        Edge: spreads compress back to mean within 1-5 minutes
        Risk: regime changes to high-vol while in a mean-reversion trade

    HIGH_VOL regime (spread trends):
        Signal: spread moves > momentum_threshold_bps in one direction
            over momentum_window consecutive updates
        Direction: FOLLOW the spread (momentum)
        Edge: large dislocations persist longer than searchers expect
        Risk: false breakout, spread reverses

    TRANSITION (regime just changed):
        No trades — wait for the new regime to establish

    Config keys:
        vol_window (int): Rolling window for volatility calculation. Default: 60
        vol_threshold (float): Realized vol above this = HIGH_VOL regime. Default: 15.0 (bps)
        entry_zscore (float): Z-score threshold for mean-reversion entries. Default: 2.0
        momentum_threshold_bps (float): Minimum spread move for momentum entry. Default: 20.0
        momentum_window (int): Consecutive updates for momentum confirmation. Default: 5
        cooldown_ticks (int): Minimum ticks between trades. Default: 10
        position_size_sol (float): Trade size. Default: 0.5
        transition_buffer (int): Ticks to wait after regime change. Default: 5
        pair (str): Trading pair. Default: "SOL/USDC"
    """

    # This strategy works with both CEX and DEX data but doesn't REQUIRE
    # both simultaneously — it can detect regimes from CEX-only or DEX-only
    # data, making it usable in single-source backtests too.
    required_sources = {Source.BINANCE_WS, Source.COINBASE_WS, Source.HELIUS_WS, Source.PARQUET_REPLAY}

    def __init__(self, config: dict) -> None:
        super().__init__(config)

        # Regime classification params
        self.vol_window: int = config.get("vol_window", 60)
        self.vol_threshold: float = config.get("vol_threshold", 15.0)

        # Mean-reversion params (low-vol regime)
        self.entry_zscore: float = config.get("entry_zscore", 2.0)

        # Momentum params (high-vol regime)
        self.momentum_threshold_bps: float = config.get("momentum_threshold_bps", 20.0)
        self.momentum_window: int = config.get("momentum_window", 5)

        # Risk management
        self.cooldown_ticks: int = config.get("cooldown_ticks", 10)
        self.position_size_sol: float = config.get("position_size_sol", 0.5)
        self.transition_buffer: int = config.get("transition_buffer", 5)
        self.pair: str = config.get("pair", "SOL/USDC")

        # Internal state
        self._cex_price: float | None = None
        self._dex_price: float | None = None
        self._spread_history: deque[float] = deque(maxlen=self.vol_window * 2)
        self._spread_direction_history: deque[float] = deque(maxlen=self.momentum_window)
        self._current_regime: Regime = Regime.TRANSITION
        self._prev_regime: Regime = Regime.TRANSITION
        self._ticks_in_regime: int = 0
        self._ticks_since_trade: int = 999
        self._last_spread: float = 0.0

    @property
    def warmup_updates(self) -> int:
        return self.vol_window + 10

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        return {
            "vol_window": (20, 120, 20),
            "vol_threshold": (5.0, 30.0, 5.0),
            "entry_zscore": (1.5, 3.0, 0.5),
            "momentum_threshold_bps": (10.0, 40.0, 5.0),
            "cooldown_ticks": (5, 20, 5),
        }

    def filters(self) -> list:
        return [self._sanity_filter]

    def _sanity_filter(self, opp: Opportunity) -> bool:
        """Reject obviously wrong opportunities."""
        return 0 < opp.spread_bps < 500

    async def before(self, update: StateUpdate) -> None:
        """Track prices and update regime classification."""
        self._updates_seen += 1
        self._ticks_since_trade += 1

        # Update prices
        if update.price:
            if update.source in {Source.BINANCE_WS, Source.COINBASE_WS}:
                self._cex_price = update.price.price
            else:
                self._dex_price = update.price.price
        elif update.pool:
            self._dex_price = update.pool.price

        # Need both prices
        if self._cex_price is None or self._dex_price is None:
            return

        # Calculate current spread
        spread_bps = (self._cex_price - self._dex_price) / self._cex_price * 10_000
        self._spread_history.append(spread_bps)

        # Track direction for momentum
        if self._last_spread != 0:
            delta = spread_bps - self._last_spread
            self._spread_direction_history.append(delta)
        self._last_spread = spread_bps

        # Classify regime
        self._classify_regime()

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Generate trading signals based on current regime."""
        if not self.is_warmed_up:
            return None

        if self._cex_price is None or self._dex_price is None:
            return None

        # Don't trade during regime transitions
        if self._current_regime == Regime.TRANSITION:
            return None

        # Cooldown
        if self._ticks_since_trade < self.cooldown_ticks:
            return None

        spread_bps = self._last_spread

        if self._current_regime == Regime.LOW_VOL:
            return self._mean_reversion_signal(spread_bps)
        elif self._current_regime == Regime.HIGH_VOL:
            return self._momentum_signal(spread_bps)

        return None

    def _classify_regime(self) -> None:
        """Classify current volatility regime from spread history."""
        if len(self._spread_history) < self.vol_window:
            self._current_regime = Regime.TRANSITION
            return

        # Compute rolling realized volatility (stdev of spread changes)
        recent = list(self._spread_history)[-self.vol_window:]
        if len(recent) < 2:
            return

        mean = sum(recent) / len(recent)
        variance = sum((s - mean) ** 2 for s in recent) / (len(recent) - 1)
        realized_vol = math.sqrt(variance)

        # Classify
        new_regime = Regime.HIGH_VOL if realized_vol > self.vol_threshold else Regime.LOW_VOL

        if self._current_regime == Regime.TRANSITION:
            self._ticks_in_regime += 1
            if self._ticks_in_regime >= self.transition_buffer:
                self._current_regime = new_regime
                self._ticks_in_regime = 0
        elif new_regime != self._current_regime:
            self._prev_regime = self._current_regime
            self._current_regime = Regime.TRANSITION
            self._ticks_in_regime = 0
        else:
            self._ticks_in_regime += 1

    def _mean_reversion_signal(self, spread_bps: float) -> Opportunity | None:
        """Low-vol regime: fade extreme spread deviations."""
        recent = list(self._spread_history)[-self.vol_window:]
        if len(recent) < 10:
            return None

        mean = sum(recent) / len(recent)
        std = math.sqrt(sum((s - mean) ** 2 for s in recent) / len(recent))
        if std < 0.1:
            return None

        zscore = (spread_bps - mean) / std

        if abs(zscore) < self.entry_zscore:
            return None

        # Fade the deviation
        if zscore > self.entry_zscore:
            # Spread is abnormally wide (CEX >> DEX) — expect it to narrow
            # Buy on DEX (cheap), effectively betting spread narrows
            direction = Direction.BUY_DEX
        else:
            # Spread is abnormally negative (DEX >> CEX) — expect it to narrow
            # Sell on DEX (expensive)
            direction = Direction.SELL_DEX

        net_spread = abs(spread_bps) - abs(mean)
        estimated_profit = (abs(net_spread) / 10_000) * self.position_size_sol

        self._opportunities_detected += 1
        self._ticks_since_trade = 0

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.STATISTICAL_ARB,
            direction=direction,
            dex_price=self._dex_price,
            reference_price=self._cex_price,
            spread_bps=round(abs(spread_bps), 2),
            estimated_profit_sol=round(estimated_profit, 6),
            pool_address="",
            dex="aggregated",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "regime": "low_vol",
                "zscore": round(zscore, 2),
                "spread_mean": round(mean, 2),
                "spread_std": round(std, 2),
                "realized_vol": round(std, 2),
                "signal": "mean_reversion",
                "volume": getattr(self, '_last_volume', None),
            },
        )

    def _momentum_signal(self, spread_bps: float) -> Opportunity | None:
        """High-vol regime: follow spread momentum."""
        if len(self._spread_direction_history) < self.momentum_window:
            return None

        recent_deltas = list(self._spread_direction_history)[-self.momentum_window:]

        # Check if all recent deltas are in the same direction
        all_positive = all(d > 0 for d in recent_deltas)
        all_negative = all(d < 0 for d in recent_deltas)

        if not (all_positive or all_negative):
            return None

        cumulative_move = sum(recent_deltas)

        if abs(cumulative_move) < self.momentum_threshold_bps:
            return None

        # Follow the momentum
        if cumulative_move > 0:
            # Spread is widening (CEX rising faster than DEX or DEX falling)
            # In momentum mode: follow the trend — sell DEX (it's falling behind)
            direction = Direction.SELL_DEX
        else:
            # Spread is narrowing rapidly (DEX catching up or overtaking)
            # Follow: buy DEX (it's gaining momentum)
            direction = Direction.BUY_DEX

        estimated_profit = (abs(cumulative_move) / 10_000) * self.position_size_sol

        self._opportunities_detected += 1
        self._ticks_since_trade = 0

        return Opportunity(
            id=str(uuid.uuid4()),
            type=OpportunityType.STATISTICAL_ARB,
            direction=direction,
            dex_price=self._dex_price,
            reference_price=self._cex_price,
            spread_bps=round(abs(spread_bps), 2),
            estimated_profit_sol=round(estimated_profit, 6),
            pool_address="",
            dex="unknown",
            pair=self.pair,
            amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
            detector_name=self.name,
            metadata={
                "regime": "high_vol",
                "cumulative_move_bps": round(cumulative_move, 2),
                "momentum_window": self.momentum_window,
                "signal": "momentum",
                "volume": getattr(self, '_last_volume', None),
            },
        )
