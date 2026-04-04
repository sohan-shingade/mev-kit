"""Abstract base class for execution sinks.

A Sink receives validated, profitable opportunities and does something
with them. What it does depends on the implementation:

- PaperTradeSink: logs theoretical P&L to SQLite
- BacktestSink: writes results to Parquet for batch analysis
- JitoBundleSink: constructs and submits a real Jito bundle
- MultiPathSink: submits through Jito + bloXroute + TPU in parallel

The Sink interface is intentionally simple. Complex execution logic
(tip optimization, multi-path routing) lives inside the Sink
implementation, not in the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mev_kit.models import ExecutionResult, Opportunity, SimulationResult


class Sink(ABC):
    """Base class for all execution sinks."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._executions: int = 0
        self._successes: int = 0

    @abstractmethod
    async def execute(
        self,
        opportunity: Opportunity,
        simulation: SimulationResult,
    ) -> ExecutionResult:
        """Execute (or log) a validated opportunity.

        Args:
            opportunity: The detected opportunity.
            simulation: The simulation result confirming profitability.

        Returns:
            ExecutionResult describing what happened.
        """
        ...

    async def setup(self) -> None:
        """Initialize resources (DB connections, API clients, etc.)."""
        pass

    async def teardown(self) -> None:
        """Clean up resources."""
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def success_rate(self) -> float:
        if self._executions == 0:
            return 0.0
        return self._successes / self._executions
