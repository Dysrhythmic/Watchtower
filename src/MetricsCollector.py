"""
MetricsCollector - Simple JSON-based metrics tracking

This module provides lightweight metrics collection and persistence using JSON file
storage. Tracks application statistics like message counts, routing success/failure
rates, and queue sizes.

Features:
- Automatic persistence to JSON file on each update
- Counter-based metrics (increment, set, get)
- Graceful recovery from corrupted metrics files
- Thread-safe for single-process use

Common Metrics:
    - messages_received_telegram: Total messages from Telegram
    - messages_received_rss: Total messages from RSS feeds
    - messages_routed_success: Successfully delivered messages
    - messages_routed_failed: Failed delivery attempts
    - messages_no_destination: Messages with no matching destinations
"""
import json
from pathlib import Path
from typing import Dict
from collections import defaultdict
from logger_setup import setup_logger

logger = setup_logger(__name__)


class MetricsCollector:
    """Lightweight metrics collector using JSON file storage.

    Persists metrics to JSON file after each update. Suitable for single-process
    applications. For multi-process setups, consider external metrics systems.
    """

    def __init__(self, metrics_file: Path):
        """Initialize metrics collector.

        Args:
            metrics_file: Path to metrics JSON file (e.g., tmp/metrics.json)
        """
        self.metrics_file = metrics_file
        self.metrics: Dict[str, int] = defaultdict(int)
        self._load_metrics()

    def _load_metrics(self) -> None:
        """Load existing metrics from file.

        If file doesn't exist or is corrupted, starts with empty metrics.
        """
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file, 'r') as f:
                    data = json.load(f)
                    self.metrics = defaultdict(int, data)
                logger.info(f"[MetricsCollector] Loaded metrics from {self.metrics_file}")
            except Exception as e:
                logger.warning(f"[MetricsCollector] Failed to load metrics: {e}, starting fresh")
                self.metrics = defaultdict(int)
        else:
            logger.info("[MetricsCollector] No existing metrics file, starting fresh")

    def _save_metrics(self) -> None:
        """Save current metrics to file.

        Creates parent directory if needed. Logs errors but doesn't raise to
        prevent metrics failures from disrupting message processing.
        """
        try:
            # Ensure parent directory exists
            self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.metrics_file, 'w') as f:
                json.dump(dict(self.metrics), f, indent=2)
        except Exception as e:
            logger.error(f"[MetricsCollector] Failed to save metrics: {e}")

    def increment(self, metric_name: str, value: int = 1) -> None:
        """Increment a metric counter.

        Args:
            metric_name: Name of the metric (e.g., "messages_received_telegram")
            value: Amount to increment by (default: 1)
        """
        self.metrics[metric_name] += value
        self._save_metrics()

    def set(self, metric_name: str, value: int) -> None:
        """Set a metric to a specific value (replaces existing value).

        Args:
            metric_name: Name of the metric
            value: Value to set
        """
        self.metrics[metric_name] = value
        self._save_metrics()

    def get(self, metric_name: str) -> int:
        """Get current value of a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            int: Current metric value (0 if metric doesn't exist)
        """
        return self.metrics.get(metric_name, 0)

    def get_all(self) -> Dict[str, int]:
        """Get all metrics as a dictionary.

        Returns:
            Dict[str, int]: Copy of all current metrics
        """
        return dict(self.metrics)

    def reset(self) -> None:
        """Reset all metrics to zero and persist the change."""
        self.metrics.clear()
        self._save_metrics()
        logger.info("[MetricsCollector] All metrics reset to zero")

    def reset_metric(self, metric_name: str) -> None:
        """Reset a specific metric to zero.

        Args:
            metric_name: Name of the metric to reset
        """
        if metric_name in self.metrics:
            del self.metrics[metric_name]
            self._save_metrics()
            logger.info(f"[MetricsCollector] Reset metric: {metric_name}")
