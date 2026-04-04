"""Pipeline monitoring with optional Prometheus metrics.

Provides counters, histograms, and gauges for observing pipeline health.
If prometheus_client is not installed, all metric operations silently no-op.

Usage:
    from mev_kit.utils.monitor import Monitor

    monitor = Monitor(enabled=True, port=9090)
    monitor.start()  # Starts HTTP server for scraping

    monitor.record_update()
    monitor.record_opportunity("cex_dex_arb", "CEXDEXArbDetector")
    monitor.record_simulation(0.045)  # duration in seconds
    monitor.record_execution("paper", success=True)
    monitor.record_profit(0.003)
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


class Monitor:
    """Pipeline monitoring with optional Prometheus metrics export.

    If prometheus_client is not installed, all methods silently no-op.
    """

    def __init__(self, enabled: bool = True, port: int = 9090) -> None:
        self.enabled = enabled and _HAS_PROMETHEUS
        self.port = port
        self._server_started = False

        if self.enabled:
            self._updates_total = Counter(
                "mev_kit_updates_total",
                "Total state updates processed",
            )
            self._opportunities_total = Counter(
                "mev_kit_opportunities_detected_total",
                "Total opportunities detected",
                ["type", "detector"],
            )
            self._simulation_duration = Histogram(
                "mev_kit_simulation_duration_seconds",
                "Time spent simulating opportunities",
                buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            )
            self._execution_total = Counter(
                "mev_kit_execution_total",
                "Total executions attempted",
                ["mode", "success"],
            )
            self._profit_total = Counter(
                "mev_kit_profit_sol_total",
                "Total profit in SOL",
            )
            self._landing_rate = Gauge(
                "mev_kit_landing_rate",
                "Current bundle landing rate",
            )

    def start(self) -> None:
        """Start the Prometheus metrics HTTP server."""
        if self.enabled and not self._server_started:
            start_http_server(self.port)
            self._server_started = True
            logger.info("monitor.started", port=self.port)

    def record_update(self) -> None:
        """Record a state update being processed."""
        if self.enabled:
            self._updates_total.inc()

    def record_opportunity(self, opp_type: str, detector: str) -> None:
        """Record an opportunity detection."""
        if self.enabled:
            self._opportunities_total.labels(type=opp_type, detector=detector).inc()

    def record_simulation(self, duration_seconds: float) -> None:
        """Record simulation duration."""
        if self.enabled:
            self._simulation_duration.observe(duration_seconds)

    def record_execution(self, mode: str, success: bool) -> None:
        """Record an execution attempt."""
        if self.enabled:
            self._execution_total.labels(mode=mode, success=str(success).lower()).inc()

    def record_profit(self, profit_sol: float) -> None:
        """Record realized or theoretical profit."""
        if self.enabled:
            self._profit_total.inc(profit_sol)

    def set_landing_rate(self, rate: float) -> None:
        """Update the current landing rate gauge."""
        if self.enabled:
            self._landing_rate.set(rate)
