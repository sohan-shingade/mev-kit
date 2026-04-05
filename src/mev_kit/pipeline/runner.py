"""Pipeline runner — orchestrates the full mev-kit pipeline.

The Pipeline wires together:
    IngestAdapters → Detector → Simulator → Sink

It handles:
    - Merging multiple ingest adapter streams into one
    - Routing state updates to the detector
    - Gating opportunities through simulation before execution
    - Circuit breaker logic (pause on consecutive losses)
    - Structured logging of every pipeline event
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import structlog

from mev_kit.adapters.ingest.base import IngestAdapter
from mev_kit.adapters.simulators.base import Simulator
from mev_kit.adapters.sinks.base import Sink
from mev_kit.models import PipelineConfig, StateUpdate
from mev_kit.strategies.base import Detector

logger = structlog.get_logger()

# Sentinel value pushed to the queue when all adapters finish
_SENTINEL = object()


class Pipeline:
    """The main mev-kit pipeline orchestrator.

    Usage:
        pipeline = Pipeline(
            config=config,
            adapters=[helius_adapter, binance_adapter],
            detector=arb_detector,
            simulator=rpc_simulator,
            sink=paper_trade_sink,
        )
        await pipeline.run()
    """

    def __init__(
        self,
        config: PipelineConfig,
        adapters: list[IngestAdapter],
        detector: Detector,
        simulator: Simulator,
        sink: Sink,
    ) -> None:
        self.config = config
        self.adapters = adapters
        self.detector = detector
        self.simulator = simulator
        self.sink = sink

        # Pipeline state
        self._running = False
        self._update_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)

        # Metrics
        self.updates_processed: int = 0
        self.opportunities_detected: int = 0
        self.opportunities_simulated: int = 0
        self.opportunities_profitable: int = 0
        self.opportunities_executed: int = 0
        self.total_profit_sol: float = 0.0
        self.consecutive_misses: int = 0
        self._start_time: datetime | None = None
        self._adapters_done: int = 0

    async def run(self) -> None:
        """Start the pipeline. Runs until stopped or circuit breaker trips."""
        self._running = True
        self._start_time = datetime.utcnow()
        self._adapters_done = 0

        logger.info(
            "pipeline.starting",
            mode=self.config.mode.value,
            strategy=self.detector.name,
            adapters=[a.name for a in self.adapters],
            sink=self.sink.name,
        )

        await self.sink.setup()

        try:
            # Start ingest adapters as background tasks
            adapter_tasks = []
            for adapter in self.adapters:
                await adapter.connect()
                adapter._running = True
                task = asyncio.create_task(
                    self._ingest_loop(adapter),
                    name=f"ingest_{adapter.name}",
                )
                adapter_tasks.append(task)

            # Run the processing loop (exits on sentinel or _running=False)
            process_task = asyncio.create_task(
                self._process_loop(),
                name="process_loop",
            )

            # Wait for all tasks
            all_tasks = [*adapter_tasks, process_task]
            done, pending = await asyncio.wait(
                all_tasks,
                return_when=asyncio.ALL_COMPLETED,
            )

            for task in done:
                exc = task.exception()
                if exc:
                    logger.error("pipeline.task_failed", task=task.get_name(), error=str(exc))

        finally:
            self._running = False
            for adapter in self.adapters:
                await adapter.disconnect()
            await self.sink.teardown()
            self._log_summary()

    async def stop(self) -> None:
        """Gracefully stop the pipeline."""
        logger.info("pipeline.stopping")
        self._running = False
        # Push sentinel so process loop exits even if queue is empty
        try:
            self._update_queue.put_nowait(_SENTINEL)
        except asyncio.QueueFull:
            pass

    async def _ingest_loop(self, adapter: IngestAdapter) -> None:
        """Pull updates from an adapter and push to the shared queue."""
        try:
            async for update in adapter.stream():
                if not self._running:
                    break
                # Use blocking put to ensure no data is dropped.
                # This also ensures fair interleaving — when the queue
                # is full, this adapter yields control so others can drain.
                await self._update_queue.put(update)
        finally:
            # Track adapter completion; push sentinel when all are done
            self._adapters_done += 1
            if self._adapters_done >= len(self.adapters):
                await self._update_queue.put(_SENTINEL)

    async def _process_loop(self) -> None:
        """Main processing loop: dequeue → detect → simulate → execute."""
        while self._running:
            try:
                item = await asyncio.wait_for(
                    self._update_queue.get(),
                    timeout=5.0,
                )
            except TimeoutError:
                continue

            # Sentinel means all adapters are done and queue is drained
            if item is _SENTINEL:
                break

            update: StateUpdate = item
            self.updates_processed += 1

            # Step 1: Detect
            opportunity = await self.detector.process(update)
            if opportunity is None:
                continue

            self.opportunities_detected += 1
            logger.info(
                "pipeline.opportunity_detected",
                type=opportunity.type.value,
                spread_bps=round(opportunity.spread_bps, 1),
                estimated_profit=round(opportunity.estimated_profit_sol, 6),
            )

            # Step 2: Simulate (if enabled)
            if self.config.simulate_before_execute:
                simulation = await self.simulator.simulate(opportunity)
                self.opportunities_simulated += 1

                if not simulation.profitable:
                    logger.debug(
                        "pipeline.opportunity_unprofitable",
                        id=opportunity.id,
                        reason=simulation.sim_error or "net_negative",
                    )
                    continue

                self.opportunities_profitable += 1
            else:
                from mev_kit.adapters.simulators.base import PassthroughSimulator
                simulation = await PassthroughSimulator({}).simulate(opportunity)

            # Step 3: Circuit breaker check
            if self.config.circuit_breaker_enabled:
                if self.consecutive_misses >= self.config.max_consecutive_misses:
                    logger.warning(
                        "pipeline.circuit_breaker_tripped",
                        consecutive_misses=self.consecutive_misses,
                    )
                    await self.stop()
                    return

            # Step 4: Execute
            result = await self.sink.execute(opportunity, simulation)
            self.opportunities_executed += 1

            if result.success:
                profit = result.realized_profit_sol or result.theoretical_profit_sol
                self.total_profit_sol += profit
                self.consecutive_misses = 0
                logger.info(
                    "pipeline.execution_success",
                    mode=result.mode.value,
                    profit_sol=round(profit, 6),
                    total_profit=round(self.total_profit_sol, 6),
                )
            else:
                self.consecutive_misses += 1
                logger.warning(
                    "pipeline.execution_failed",
                    error=result.error,
                    consecutive_misses=self.consecutive_misses,
                )

    def _log_summary(self) -> None:
        """Log a summary of the pipeline run."""
        elapsed = (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0
        logger.info(
            "pipeline.summary",
            elapsed_seconds=round(elapsed, 1),
            updates_processed=self.updates_processed,
            opportunities_detected=self.opportunities_detected,
            opportunities_profitable=self.opportunities_profitable,
            opportunities_executed=self.opportunities_executed,
            total_profit_sol=round(self.total_profit_sol, 6),
            detection_rate=(
                f"{self.opportunities_detected / max(1, self.updates_processed) * 100:.2f}%"
            ),
        )
