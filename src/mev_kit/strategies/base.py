"""Abstract base class for MEV opportunity detectors (strategies).

A Detector consumes StateUpdate objects and emits Opportunity objects
when it identifies an exploitable condition. Detectors are stateful —
they maintain internal state (e.g., latest CEX price, latest DEX price)
and check for opportunities on every update.

Detectors never know if they're running against live data or replay.
They receive the same StateUpdate type in both cases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mev_kit.models import Opportunity, StateUpdate


class Detector(ABC):
    """Base class for all MEV opportunity detectors.

    Subclasses implement process() which receives every StateUpdate
    and optionally returns an Opportunity if one is detected.

    Example:
        class MyArbDetector(Detector):
            async def process(self, update: StateUpdate) -> Opportunity | None:
                # Update internal state
                # Check for opportunity
                # Return Opportunity or None
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._opportunities_detected: int = 0

    @abstractmethod
    async def process(self, update: StateUpdate) -> Opportunity | None:
        """Process a state update and optionally detect an opportunity.

        Args:
            update: A normalized state update from any ingest adapter.

        Returns:
            An Opportunity if one is detected, None otherwise.
        """
        ...

    @property
    def name(self) -> str:
        """Human-readable detector name for logging and metrics."""
        return self.__class__.__name__

    @property
    def opportunities_detected(self) -> int:
        return self._opportunities_detected
