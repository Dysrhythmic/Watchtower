"""
MetricsCollector - Simple JSON-based metrics tracking

This module provides lightweight metrics collection and persistence using JSON file
storage. Tracks application statistics like message counts, routing success/failure
rates, and queue sizes.

Features:
- Periodic persistence to JSON file (every 60 seconds by default)
- Counter-based metrics (increment, set, get)
- Thread-safe for single-process use
- Force save on shutdown for clean exit

Performance:
    Uses periodic saves instead of immediate persistence to reduce disk I/O:
    - Default: Save every 60 seconds (configurable)
    - Max data loss: 60 seconds worth of metrics on crash
    - Significant performance gain for high-volume message processing
    - SSD-friendly for Raspberry Pi and similar devices

Metrics Persistence:
    - Saved to metrics.json at shutdown for logging/archival purposes
    - On startup each session starts fresh at zero

Common Metrics:
    - messages_received_telegram: Messages from Telegram
    - messages_received_rss: Messages from RSS feeds
    - total_msgs_routed_success: Successfully delivered messages
    - total_msgs_routed_failed: Failed delivery attempts
    - total_msgs_no_destination: Messages with no matching destinations
    - telegram_missed_messages: Messages found via polling
    - time_ran: Session duration in seconds
"""
import json
import time
from pathlib import Path
from typing import Dict
from collections import defaultdict
from LoggerSetup import setup_logger

_logger = setup_logger(__name__)


class MetricsCollector:
    """Lightweight metrics collector using JSON file storage with periodic saves.

    Persists metrics to JSON file every SAVE_INTERVAL seconds to balance data
    integrity with performance. Suitable for single-process applications running
    on devices like Raspberry Pi where minimizing disk writes is important.

    Attributes:
        SAVE_INTERVAL: Seconds between automatic saves (default: 60)
        metrics_file: Path to metrics JSON file
        metrics: Dictionary of metric names to values
    """

    SAVE_INTERVAL = 60  # seconds - save metrics every minute

    def __init__(self, metrics_file: Path):
        """Initialize metrics collector.

        Metrics are per-session (reset on each startup). The metrics file is used
        for saving at shutdown but is not loaded on startup.

        Args:
            metrics_file: Path to metrics JSON file (e.g., tmp/metrics.json)
        """
        self.metrics_file = metrics_file
        self.metrics: Dict[str, int] = defaultdict(int)
        self._last_save_time = time.time()
        self._dirty = False  # Track if metrics changed since last save
        _logger.info("[MetricsCollector] Starting with fresh metrics")

    def _save_metrics(self) -> None:
        """Save current metrics to file immediately.

        Creates parent directory if needed. Logs errors but doesn't raise to
        prevent metrics failures from disrupting message processing.

        Note:
            Called by _maybe_save_metrics() for periodic saves and force_save()
            for shutdown. Not called directly by increment/set anymore.
        """
        try:
            # Ensure parent directory exists
            self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.metrics_file, 'w') as f:
                json.dump(dict(self.metrics), f, indent=2)

            _logger.debug(f"[MetricsCollector] Saved metrics to {self.metrics_file}")
        except Exception as e:
            _logger.error(f"[MetricsCollector] Failed to save metrics: {e}")

    def _maybe_save_metrics(self) -> None:
        """Save metrics if interval has passed since last save.

        Only saves if:
        1. Metrics have changed (_dirty flag is True)
        2. At least SAVE_INTERVAL seconds have passed since last save

        This reduces disk I/O while ensuring metrics are persisted regularly.
        """
        if self._dirty and (time.time() - self._last_save_time) >= self.SAVE_INTERVAL:
            self._save_metrics()
            self._last_save_time = time.time()
            self._dirty = False

    def force_save(self) -> None:
        """Force immediate save of metrics regardless of interval.

        Should be called on application shutdown to ensure all metrics are
        persisted. Safe to call multiple times.

        Example:
            >>> collector.force_save()  # Called during shutdown
        """
        if self._dirty:
            self._save_metrics()
            self._last_save_time = time.time()
            self._dirty = False
            _logger.info("[MetricsCollector] Forced save on shutdown")

    def increment(self, metric_name: str, value: int = 1) -> None:
        """Increment a metric counter.

        Marks metrics as dirty and triggers periodic save if interval elapsed.
        Does NOT immediately save to disk - use force_save() for that.
        """
        self.metrics[metric_name] += value
        self._dirty = True
        self._maybe_save_metrics()

    def set(self, metric_name: str, value: int) -> None:
        """Set a metric to a specific value (replaces existing value).

        Marks metrics as dirty and triggers periodic save if interval elapsed.
        Does NOT immediately save to disk - use force_save() for that.
        """
        self.metrics[metric_name] = value
        self._dirty = True
        self._maybe_save_metrics()

    def get(self, metric_name: str) -> int:
        """Get current value of a metric (returns 0 if metric doesn't exist)."""
        return self.metrics.get(metric_name, 0)

    def get_all(self) -> Dict[str, int]:
        """Get all metrics as a dictionary."""
        return dict(self.metrics)

    def reset(self) -> None:
        """Reset all metrics to zero and force immediate save.

        This is a significant operation that warrants immediate persistence.
        """
        self.metrics.clear()
        self._dirty = True
        self.force_save()
        _logger.info("[MetricsCollector] All metrics reset to zero")

    def reset_metric(self, metric_name: str) -> None:
        """Reset a specific metric to zero and force immediate save.

        Args:
            metric_name: Name of the metric to reset

        This is a significant operation that warrants immediate persistence.
        """
        if metric_name in self.metrics:
            del self.metrics[metric_name]
            self._dirty = True
            self.force_save()
            _logger.info(f"[MetricsCollector] Reset metric: {metric_name}")
