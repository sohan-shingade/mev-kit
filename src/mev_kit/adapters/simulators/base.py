"""Abstract base class for pre-execution simulators.

Simulators validate opportunities before they reach a Sink. They answer:
"Would this transaction succeed, and what would the net profit be?"

Free tier: RPCSimulator calls simulateTransaction via Helius.
Pro tier: LocalValidatorSimulator forks mainnet state locally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mev_kit.models import Opportunity, SimulationResult


class Simulator(ABC):
    """Base class for all pre-execution simulators."""

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        """Simulate execution of an opportunity.

        Args:
            opportunity: A detected opportunity to validate.

        Returns:
            SimulationResult with profitability assessment.
        """
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class PassthroughSimulator(Simulator):
    """Simulator that skips simulation — passes everything through.

    Use for backtesting when you want raw detection counts without
    simulation overhead, or when simulation isn't available.
    """

    async def simulate(self, opportunity: Opportunity) -> SimulationResult:
        return SimulationResult(
            opportunity_id=opportunity.id,
            profitable=True,
            net_profit_sol=opportunity.estimated_profit_sol,
            simulated=False,
        )
