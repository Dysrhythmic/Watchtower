import logging
import json
from pathlib import Path
from typing import Dict
from collections import defaultdict

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MetricsCollector:
    """Lightweight metrics collector using JSON file storage."""

    def __init__(self, metrics_file: Path):
        """Initialize metrics collector.

        Args:
            metrics_file: Path to metrics JSON file (e.g., tmp/metrics.json)
        """
        self.metrics_file = metrics_file
        self.metrics: Dict[str, int] = defaultdict(int)
        self._load_metrics()

    def _load_metrics(self):
        """Load existing metrics from file."""
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

    def _save_metrics(self):
        """Save current metrics to file."""
        try:
            # Ensure parent directory exists
            self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.metrics_file, 'w') as f:
                json.dump(dict(self.metrics), f, indent=2)
        except Exception as e:
            logger.error(f"[MetricsCollector] Failed to save metrics: {e}")

    def increment(self, metric_name: str, value: int = 1):
        """Increment a metric counter.

        Args:
            metric_name: Name of the metric (e.g., "messages_received_telegram")
            value: Amount to increment by (default: 1)
        """
        self.metrics[metric_name] += value
        self._save_metrics()

    def set(self, metric_name: str, value: int):
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
            int: Current metric value
        """
        return self.metrics.get(metric_name, 0)

    def get_all(self) -> Dict[str, int]:
        """Get all metrics.

        Returns:
            Dict[str, int]: All current metrics
        """
        return dict(self.metrics)

    def reset(self):
        """Reset all metrics to zero."""
        self.metrics.clear()
        self._save_metrics()
        logger.info("[MetricsCollector] All metrics reset to zero")

    def reset_metric(self, metric_name: str):
        """Reset a specific metric to zero.

        Args:
            metric_name: Name of the metric to reset
        """
        if metric_name in self.metrics:
            del self.metrics[metric_name]
            self._save_metrics()
            logger.info(f"[MetricsCollector] Reset metric: {metric_name}")
