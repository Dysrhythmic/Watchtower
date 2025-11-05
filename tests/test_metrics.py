import unittest
import sys
import os
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MetricsCollector import MetricsCollector
from MessageData import MessageData


class TestMetricsCollector(unittest.TestCase):
    """Test MetricsCollector."""

    def setUp(self):
        """Create MetricsCollector with temp file."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        self.metrics = MetricsCollector(Path(self.temp_file.name))

    def tearDown(self):
        """Clean up temp file."""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_increment_metric(self):
        """Test incrementing a metric."""
        self.metrics.increment("test_metric")
        self.assertEqual(self.metrics.get("test_metric"), 1)

        self.metrics.increment("test_metric")
        self.assertEqual(self.metrics.get("test_metric"), 2)

    def test_increment_by_value(self):
        """Test incrementing by a specific value."""
        self.metrics.increment("test_metric", 5)
        self.assertEqual(self.metrics.get("test_metric"), 5)

    def test_get_all_metrics(self):
        """Test getting all metrics."""
        self.metrics.increment("metric1")
        self.metrics.increment("metric2")

        all_metrics = self.metrics.get_all()
        self.assertEqual(len(all_metrics), 2)
        self.assertIn("metric1", all_metrics)
        self.assertIn("metric2", all_metrics)

    def test_save_and_load_json(self):
        """Test saving to and loading from JSON."""
        self.metrics.increment("test_metric", 10)

        # Create new instance with same file
        metrics2 = MetricsCollector(Path(self.temp_file.name))
        self.assertEqual(metrics2.get("test_metric"), 10)

    def test_reset_all_metrics(self):
        """Test resetting all metrics."""
        self.metrics.increment("metric1")
        self.metrics.increment("metric2")

        self.metrics.reset()
        self.assertEqual(len(self.metrics.get_all()), 0)

    def test_get_nonexistent_metric(self):
        """Test getting nonexistent metric returns 0."""
        value = self.metrics.get("nonexistent")
        self.assertEqual(value, 0)

    def test_increment_creates_metric(self):
        """Test incrementing creates new metric if doesn't exist."""
        self.metrics.increment("new_metric")
        self.assertEqual(self.metrics.get("new_metric"), 1)

    def test_persistence_after_reset(self):
        """Test metrics persist to file after reset."""
        self.metrics.increment("test", 5)
        self.metrics.reset()

        # Load from file
        metrics2 = MetricsCollector(Path(self.temp_file.name))
        self.assertEqual(len(metrics2.get_all()), 0)

    def test_increment_large_value(self):
        """Test incrementing by large value."""
        self.metrics.increment("large", 1000000)
        self.assertEqual(self.metrics.get("large"), 1000000)

    def test_multiple_increments_same_metric(self):
        """Test multiple increments accumulate correctly."""
        for i in range(10):
            self.metrics.increment("counter")

        self.assertEqual(self.metrics.get("counter"), 10)

    def test_concurrent_metrics(self):
        """Test tracking multiple different metrics."""
        self.metrics.increment("messages_sent", 5)
        self.metrics.increment("messages_received", 3)
        self.metrics.increment("messages_queued", 2)

        self.assertEqual(self.metrics.get("messages_sent"), 5)
        self.assertEqual(self.metrics.get("messages_received"), 3)
        self.assertEqual(self.metrics.get("messages_queued"), 2)

    def test_set_metric(self):
        """Test setting a metric to a specific value."""
        self.metrics.set("time_ran", 100)
        self.assertEqual(self.metrics.get("time_ran"), 100)

        # Set again - should replace, not add
        self.metrics.set("time_ran", 50)
        self.assertEqual(self.metrics.get("time_ran"), 50)

    def test_set_vs_increment(self):
        """Test that set replaces while increment adds."""
        # Increment adds
        self.metrics.increment("counter", 10)
        self.assertEqual(self.metrics.get("counter"), 10)
        self.metrics.increment("counter", 5)
        self.assertEqual(self.metrics.get("counter"), 15)

        # Set replaces
        self.metrics.set("timer", 100)
        self.assertEqual(self.metrics.get("timer"), 100)
        self.metrics.set("timer", 50)
        self.assertEqual(self.metrics.get("timer"), 50)  # Replaced, not added

    def test_metrics_counters_after_flow(self):
        """Test verify messages_received/sent incremented after message flow."""
        self.metrics.increment("messages_received_telegram")
        self.metrics.increment("messages_sent_discord")
        self.metrics.increment("messages_sent_discord")

        self.assertEqual(self.metrics.get("messages_received_telegram"), 1)
        self.assertEqual(self.metrics.get("messages_sent_discord"), 2)

    def test_metrics_ocr_processed_counter(self):
        """Test OCR processed metric increments correctly."""
        self.metrics.increment("ocr_processed")
        self.metrics.increment("ocr_processed")
        self.metrics.increment("ocr_processed")

        self.assertEqual(self.metrics.get("ocr_processed"), 3)

    def test_metrics_time_ran_timer(self):
        """Test time_ran timer metric uses set (not increment)."""
        # First session
        self.metrics.set("time_ran", 100)
        self.assertEqual(self.metrics.get("time_ran"), 100)

        # Second session should replace, not add
        self.metrics.set("time_ran", 200)
        self.assertEqual(self.metrics.get("time_ran"), 200)
        self.assertNotEqual(self.metrics.get("time_ran"), 300)


class TestMetricsIntegration(unittest.TestCase):
    """Test metrics integration with message flow."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_sent_metric_incremented(self, mock_config_class, mock_telegram_client):
        """Test ocr_sent metric is incremented when OCR messages are sent."""
        from Watchtower import Watchtower
        import asyncio

        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path(tempfile.mkdtemp())
        mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
        mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
        mock_config.project_root = mock_config.tmp_dir
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"
        mock_config.get_all_channel_ids = Mock(return_value=set())
        mock_config.webhooks = []
        mock_config_class.return_value = mock_config

        # Create isolated metrics
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

        # Create message with OCR
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=False
        )
        message_data.ocr_raw = "Some OCR text"

        # Mock Discord send
        with patch.object(app.discord, 'send_message', return_value=True):
            destination = {
                'type': 'discord',
                'name': 'Test',
                'webhook_url': 'http://test.com',
                'parser': {}
            }
            content = app.discord.format_message(message_data, destination)
            asyncio.run(app._send_to_discord(message_data, destination, content, False))

        # Verify ocr_sent incremented
        self.assertEqual(app.metrics.get("ocr_sent"), 1)

        # Cleanup
        os.unlink(temp_metrics.name)
        import shutil
        shutil.rmtree(mock_config.tmp_dir)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_sent_not_incremented_without_ocr(self, mock_config_class, mock_telegram_client):
        """Test ocr_sent metric NOT incremented for non-OCR messages."""
        from Watchtower import Watchtower
        import asyncio

        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path(tempfile.mkdtemp())
        mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
        mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
        mock_config.project_root = mock_config.tmp_dir
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"
        mock_config.get_all_channel_ids = Mock(return_value=set())
        mock_config.webhooks = []
        mock_config_class.return_value = mock_config

        # Create isolated metrics
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

        # Create message WITHOUT OCR
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=False
        )

        # Mock Discord send
        with patch.object(app.discord, 'send_message', return_value=True):
            destination = {
                'type': 'discord',
                'name': 'Test',
                'webhook_url': 'http://test.com',
                'parser': {}
            }
            content = app.discord.format_message(message_data, destination)
            asyncio.run(app._send_to_discord(message_data, destination, content, False))

        # Verify ocr_sent NOT incremented
        self.assertEqual(app.metrics.get("ocr_sent"), 0)

        # Cleanup
        os.unlink(temp_metrics.name)
        import shutil
        shutil.rmtree(mock_config.tmp_dir)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_time_ran_metric_per_session(self, mock_config_class, mock_telegram_client):
        """Test time_ran metric is per-session, not cumulative."""
        from Watchtower import Watchtower
        import asyncio
        import time

        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path(tempfile.mkdtemp())
        mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
        mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
        mock_config.project_root = mock_config.tmp_dir
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"
        mock_config.get_all_channel_ids = Mock(return_value=set())
        mock_config.webhooks = []
        mock_config_class.return_value = mock_config

        # Create isolated metrics
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        # First session: 10 seconds
        app1 = Watchtower(sources=[], metrics=isolated_metrics)
        app1.telegram.client.is_connected = lambda: False
        app1._start_time = time.time() - 10
        asyncio.run(app1.shutdown())

        first_time_ran = isolated_metrics.get("time_ran")
        self.assertGreaterEqual(first_time_ran, 9)
        self.assertLessEqual(first_time_ran, 12)

        # Second session: 5 seconds (should REPLACE, not add)
        app2 = Watchtower(sources=[], metrics=isolated_metrics)
        app2.telegram.client.is_connected = lambda: False
        app2._start_time = time.time() - 5
        asyncio.run(app2.shutdown())

        second_time_ran = isolated_metrics.get("time_ran")
        # Should be ~5, NOT ~15 (if cumulative)
        self.assertGreaterEqual(second_time_ran, 4)
        self.assertLessEqual(second_time_ran, 7)

        # Cleanup
        os.unlink(temp_metrics.name)
        import shutil
        shutil.rmtree(mock_config.tmp_dir)


if __name__ == '__main__':
    unittest.main()
