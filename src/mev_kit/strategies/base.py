"""Base class for MEV opportunity detectors.

Inspired by:
- Artemis (Paradigm): process_event() -> Vec<Action>, sync_state()
- Hummingbot: markets class attribute for data source declaration
- Jesse.trade: filters(), before()/after() hooks
- Backtrader: params tuple for optimizer-friendly hyperparameters

The Detector ABC provides:
- process(): Core detection logic (must override)
- required_sources: Declare what data feeds you need
- sync_state(): One-time initialization before the event loop
- before()/after(): Per-update hooks for state tracking
- filters(): Validation functions applied after detection
- hyperparameters(): Parameter ranges for backtesting optimization
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from mev_kit.models import Opportunity, Source, StateUpdate


class Detector(ABC):
    """Base class for all MEV opportunity detectors.

    Subclass this to implement your own detection strategy.
    At minimum, override `process()`. Optionally override lifecycle
    hooks and declare required data sources.

    Example:
        class MyDetector(Detector):
            required_sources = {Source.BINANCE_WS, Source.HELIUS_WS}

            async def process(self, update: StateUpdate) -> Opportunity | None:
                # Your detection logic here
                return None
    """

    # Declare what data sources this detector needs.
    # The pipeline uses this to validate adapter configuration.
    # Override in subclass. Empty set = accepts any source.
    required_sources: set[Source] = set()

    def __init__(self, config: dict) -> None:
        self.config = config
        self._opportunities_detected: int = 0
        self._updates_seen: int = 0

    # ── Core detection (MUST override) ──

    @abstractmethod
    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a state update and optionally detect an opportunity.

        This is the core detection method. Receives every StateUpdate
        from the pipeline's ingest adapters. Return an Opportunity if
        you detect one, or None to skip.

        For detectors that can emit multiple opportunities per update,
        override `process_batch()` instead.

        Args:
            update: A state update from any connected data source.

        Returns:
            An Opportunity if detected, None otherwise.
        """
        ...

    # ── Multi-opportunity detection (optional) ──

    async def process_batch(self, update: StateUpdate) -> list[Opportunity]:
        """Process a state update and return zero or more opportunities.

        Override this instead of process() if a single update can
        trigger multiple opportunities (e.g., arb across multiple pools).

        Default implementation wraps process() into a list.
        """
        result = await self.process(update)
        return [result] if result is not None else []

    # ── Lifecycle hooks (optional overrides) ──

    async def sync_state(self) -> None:
        """Initialize state before the event loop starts.

        Called once after adapters connect but before events flow.
        Use this to fetch initial on-chain state, load historical
        data, or warm up any models.

        Example:
            async def sync_state(self):
                self._pool_reserves = await self._fetch_reserves()
        """

    async def before(self, update: StateUpdate) -> None:
        """Called before process() on every update.

        Use for state tracking that should happen regardless
        of whether an opportunity is detected. Good for:
        - Updating moving averages
        - Tracking price history
        - Logging state changes
        """

    async def after(
        self, update: StateUpdate, opportunities: list[Opportunity]
    ) -> None:
        """Called after process() on every update.

        Receives the list of detected opportunities (may be empty).
        Use for:
        - Updating metrics
        - Applying cooldowns after detection
        - Logging detection rates
        """

    # ── Filters (optional) ──

    def filters(self) -> list:
        """Return a list of filter functions applied after detection.

        Each filter takes an Opportunity and returns True to keep it,
        False to discard. Filters run in order; first rejection stops.

        Example:
            def filters(self):
                return [self._staleness_filter, self._min_profit_filter]

            def _staleness_filter(self, opp: Opportunity) -> bool:
                age_ms = (datetime.now(UTC) - opp.detected_at).total_seconds() * 1000
                return age_ms < 500  # reject stale opportunities

            def _min_profit_filter(self, opp: Opportunity) -> bool:
                return opp.estimated_profit_sol > 0.001
        """
        return []

    # ── Hyperparameters for optimization (optional) ──

    def hyperparameters(self) -> dict[str, tuple[float, float, float]]:
        """Declare optimizable parameter ranges for backtesting.

        Returns a dict of parameter name -> (min, max, step).
        The backtesting engine can sweep these to find optimal values.

        Example:
            def hyperparameters(self):
                return {
                    "min_spread_bps": (5.0, 50.0, 5.0),
                    "position_size_sol": (0.01, 1.0, 0.1),
                }
        """
        return {}

    # ── Properties ──

    @property
    def name(self) -> str:
        """Human-readable detector name for logging."""
        return self.__class__.__name__

    @property
    def opportunities_detected(self) -> int:
        return self._opportunities_detected

    @property
    def updates_seen(self) -> int:
        return self._updates_seen

    @property
    def warmup_updates(self) -> int:
        """Number of updates needed before detection is reliable.

        Override if your detector needs a warm-up period
        (e.g., building a price history for a moving average).
        Default: 0 (no warm-up needed).
        """
        return 0

    @property
    def is_warmed_up(self) -> bool:
        """Whether enough updates have been seen for reliable detection."""
        return self._updates_seen >= self.warmup_updates
