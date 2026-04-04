"""Abstract base class for data ingestion adapters.

Every data source (Helius, Binance, Geyser, Parquet replay) implements
this interface. The pipeline doesn't know or care which adapter is
running — it just consumes StateUpdate objects from the queue.

To create a pro-tier adapter (e.g., GeyserAdapter), implement this ABC
and register it in the adapter registry. Zero changes to strategy code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from mev_kit.models import StateUpdate


class IngestAdapter(ABC):
    """Base class for all data ingestion adapters.

    Lifecycle:
        1. __init__ with config
        2. connect() — establish connections, authenticate
        3. stream() — yield StateUpdate objects indefinitely
        4. disconnect() — clean shutdown

    Adapters must handle reconnection internally. If a WebSocket drops,
    the adapter reconnects and resumes streaming without the pipeline
    knowing anything happened.
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        self._running = False

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source.

        Raises:
            ConnectionError: If the data source is unreachable.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close connections and release resources."""
        ...

    @abstractmethod
    async def stream(self) -> AsyncIterator[StateUpdate]:
        """Yield StateUpdate objects from this data source.

        This is an async generator that runs indefinitely until
        disconnect() is called. It must handle reconnection internally.

        Yields:
            StateUpdate objects normalized from the raw data source.
        """
        ...

    async def __aenter__(self) -> IngestAdapter:
        await self.connect()
        self._running = True
        return self

    async def __aexit__(self, *args: object) -> None:
        self._running = False
        await self.disconnect()

    @property
    def name(self) -> str:
        """Human-readable adapter name for logging."""
        return self.__class__.__name__
