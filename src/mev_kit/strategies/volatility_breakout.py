"""Volatility Breakout Detector — Bollinger Band squeeze-and-break strategy.

Monitors the CEX-DEX spread and detects when volatility contracts (squeeze)
followed by a rapid expansion (breakout). This is a classic volatility
regime-change detector adapted for MEV: when spreads have been tight and
suddenly blow out, there is a high-probability directional move underway
that MEV searchers can exploit before the spread mean-reverts.

The core insight: low-volatility regimes in CEX-DEX spreads indicate
equilibrium. When that equilibrium breaks, the first movers capture the
spread before market makers re-price. This detector identifies the exact
moment of regime change.

Algorithm:
    1. Track a rolling window of CEX-DEX spread values
    2. Compute Bollinger Bands (mean +/- k*std) on the spread
    3. Measure "bandwidth" (band width / mean) as volatility proxy
    4. Detect SQUEEZE: bandwidth falls below squeeze_threshold
    5. Detect BREAKOUT: after squeeze, spread pierces upper or lower band
    6. Emit opportunity in the direction of the breakout

REQUIRED_DATA_SOURCES:
    - Source.BINANCE_WS: CEX reference price
    - Source.HELIUS_WS or Source.PARQUET_REPLAY: DEX price feed

NOTE: All state tracking is done in process() because the Pipeline runner
      does NOT call before()/after() hooks (pipeline bug documented).
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from enum import StrEnum

from mev_kit.models import (
    Direction,
    Opportunity,
    OpportunityType,
    Source,
    StateUpdate,
)
from mev_kit.strategies.base import Detector


class Phase(StrEnum):
    """Detector state machine phases."""
    IDLE = "idle"
    SQUEEZE = "squeeze"
    BREAKOUT = "breakout"


class VolatilityBreakoutDetector(Detector):
    """Bollinger Band squeeze-and-break detector for CEX-DEX spreads.

    Monitors the spread between CEX and DEX prices. When the spread
    volatility contracts (Bollinger Band squeeze) and then rapidly
    expands (breakout), emits a directional opportunity.

    Config keys:
        window_size (int): Rolling window for Bollinger Bands. Default: 30
        bb_multiplier (float): Std dev multiplier for bands. Default: 2.0
        squeeze_threshold (float): Bandwidth below this = squeeze. Default: 0.3
        min_squeeze_bars (int): Min bars in squeeze before breakout counts. Default: 5
        breakout_spread_bps (float): Min net spread to trigger. Default: 3.0
        fee_bps (float): DEX swap fee. Default: 30.0
        position_size_sol (float): Trade size. Default: 0.05
        cooldown_ticks (int): Ticks to suppress after signal. Default: 5
        pair (str): Trading pair. Default: "SOL/USDC"
    """

    required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

    # Explicitly declare CEX and DEX source sets for dual-source detection
    CEX_SOURCES = {Source.BINANCE_WS}
    DEX_SOURCES = {Source.HELIUS_WS, Source.PARQUET_REPLAY}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.window_size: int = config.get("window_size", 30)
        self.bb_multiplier: float = config.get("bb_multiplier", 2.0)
        self.squeeze_threshold: float = config.get("squeeze_threshold", 0.3)
        self.min_squeeze_bars: int = config.get("min_squeeze_bars", 5)
        self.breakout_spread_bps: float = config.get("breakout_spread_bps", 3.0)
        self.fee_bps: float = config.get("fee_bps", 30.0)
        self.position_size_sol: float = config.get("position_size_sol", 0.05)
        self.cooldown_ticks: int = config.get("cooldown_ticks", 5)
        self.pair: str = config.get("pair", "SOL/USDC")

        # Internal state
        self._cex_price: float | None = None
        self._dex_price: float | None = None
        self._spread_history: deque[float] = deque(maxlen=self.window_size)

        # Running statistics for O(1) mean/std computation
        self._sum: float = 0.0
        self._sum_sq: float = 0.0

        # State machine
        self._phase: Phase = Phase.IDLE
        self._squeeze_bars: int = 0
        self._ticks_since_signal: int = self.cooldown_ticks  # start ready
        self._breakouts_detected: int = 0

    @property
    def warmup_updates(self) -> int:
        """Need a full window of spread data for reliable bands."""
        return self.window_size

    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Detect volatility breakout using Bollinger Band squeeze pattern.

        All state tracking is done here (not in before()) because the
        pipeline runner does not call lifecycle hooks.
        """
        self._updates_seen += 1

        # --- State tracking (normally would be in before()) ---
        if update.source == Source.BINANCE_WS and update.price:
            self._cex_price = update.price.price
        elif update.pool:
            self._dex_price = update.pool.price
        elif update.price and update.source != Source.BINANCE_WS:
            self._dex_price = update.price.price

        # Record spread observation when both prices available
        if self._cex_price and self._dex_price and self._cex_price > 0:
            spread_bps = (
                (self._dex_price - self._cex_price) / self._cex_price * 10_000
            )
            # Maintain running sums for O(1) statistics
            if len(self._spread_history) == self._spread_history.maxlen:
                old = self._spread_history[0]
                self._sum -= old
                self._sum_sq -= old * old
            self._spread_history.append(spread_bps)
            self._sum += spread_bps
            self._sum_sq += spread_bps * spread_bps

        # --- Detection logic ---
        if not self.is_warmed_up:
            return None
        if self._cex_price is None or self._dex_price is None:
            return None

        n = len(self._spread_history)
        if n < self.window_size:
            return None

        # Compute Bollinger Band statistics
        mean = self._sum / n
        variance = (self._sum_sq / n) - (mean * mean)
        if variance <= 0:
            return None
        std = math.sqrt(variance)

        upper_band = mean + self.bb_multiplier * std
        lower_band = mean - self.bb_multiplier * std

        # Bandwidth = (upper - lower) / |mean| as volatility proxy
        abs_mean = max(abs(mean), 0.01)
        bandwidth = (upper_band - lower_band) / abs_mean

        current_spread = self._spread_history[-1]
        self._ticks_since_signal += 1

        # State machine transitions
        if self._phase == Phase.IDLE:
            if bandwidth < self.squeeze_threshold:
                self._phase = Phase.SQUEEZE
                self._squeeze_bars = 1
            return None

        elif self._phase == Phase.SQUEEZE:
            if bandwidth < self.squeeze_threshold:
                self._squeeze_bars += 1
                return None
            else:
                # Volatility expanded -- check for breakout
                if self._squeeze_bars >= self.min_squeeze_bars:
                    self._phase = Phase.BREAKOUT
                    # Fall through to breakout detection below
                else:
                    # Squeeze was too short, reset
                    self._phase = Phase.IDLE
                    self._squeeze_bars = 0
                    return None

        # BREAKOUT phase: check if spread pierces a band
        if self._phase == Phase.BREAKOUT:
            self._phase = Phase.IDLE  # Reset after evaluating
            self._squeeze_bars = 0

            # Enforce cooldown
            if self._ticks_since_signal < self.cooldown_ticks:
                return None

            pierced_upper = current_spread > upper_band
            pierced_lower = current_spread < lower_band

            if not (pierced_upper or pierced_lower):
                return None

            # Net spread after fees
            net_spread_bps = abs(current_spread) - self.fee_bps
            if net_spread_bps < self.breakout_spread_bps:
                return None

            # Direction: upper band break = DEX expensive = sell DEX
            #            lower band break = DEX cheap = buy DEX
            direction = Direction.SELL_DEX if pierced_upper else Direction.BUY_DEX

            estimated_profit = (
                (net_spread_bps / 10_000)
                * self.position_size_sol
                * self._cex_price
            )

            self._ticks_since_signal = 0
            self._breakouts_detected += 1
            self._opportunities_detected += 1

            return Opportunity(
                id=str(uuid.uuid4()),
                type=OpportunityType.STATISTICAL_ARB,
                direction=direction,
                dex_price=self._dex_price,
                reference_price=self._cex_price,
                spread_bps=round(abs(current_spread), 2),
                estimated_profit_sol=round(
                    estimated_profit / max(self._cex_price, 0.01), 6
                ),
                pool_address="",
                dex="raydium",
                pair=self.pair,
                amount_in_lamports=int(self.position_size_sol * 1_000_000_000),
                detector_name=self.name,
                metadata={
                    "phase": "breakout",
                    "squeeze_bars": self._squeeze_bars,
                    "bandwidth": round(bandwidth, 4),
                    "bb_upper": round(upper_band, 2),
                    "bb_lower": round(lower_band, 2),
                    "bb_mean": round(mean, 2),
                    "bb_std": round(std, 4),
                    "current_spread_bps": round(current_spread, 2),
                    "net_spread_bps": round(net_spread_bps, 2),
                    "breakout_direction": "upper" if pierced_upper else "lower",
                    "total_breakouts": self._breakouts_detected,
                },
            )

        return None

    def filters(self) -> list:
        """Post-detection sanity filters."""
        return [self._spread_sanity_filter, self._bandwidth_filter]

    def _spread_sanity_filter(self, opp: Opportunity) -> bool:
        """Reject absurd spreads that indicate data errors."""
        return opp.spread_bps < 500  # 5% spread is almost certainly bad data

    def _bandwidth_filter(self, opp: Opportunity) -> bool:
        """Reject breakouts where bandwidth expansion is too extreme."""
        bw = opp.metadata.get("bandwidth", 0.0)
        return bw < 50.0  # Extreme bandwidth = likely data artifact

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        """Declare tunable parameters for backtesting optimization."""
        return {
            "window_size": (10.0, 100.0, 10.0),
            "bb_multiplier": (1.0, 3.0, 0.5),
            "squeeze_threshold": (0.1, 1.0, 0.1),
            "min_squeeze_bars": (2.0, 15.0, 1.0),
            "breakout_spread_bps": (1.0, 20.0, 1.0),
            "position_size_sol": (0.01, 1.0, 0.1),
            "cooldown_ticks": (1.0, 15.0, 1.0),
        }
