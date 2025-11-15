"""Test MetricsCollector - Usage statistics tracking and persistence."""
import sys
import os
import json
import tempfile
import time
from unittest.mock import Mock, patch
from pathlib import Path
from datetime import datetime, timezone
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MetricsCollector import MetricsCollector
from MessageData import MessageData


@pytest.fixture
def metrics_collector():
    """Create MetricsCollector with temp file."""
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_file.close()
    metrics = MetricsCollector(Path(temp_file.name))
    yield metrics, temp_file.name
    if os.path.exists(temp_file.name):
        os.unlink(temp_file.name)


def test_increment_metric(metrics_collector):
    """Test incrementing a metric."""
    metrics, _ = metrics_collector
    metrics.increment("test_metric")
    assert metrics.get("test_metric") == 1

    metrics.increment("test_metric")
    assert metrics.get("test_metric") == 2


def test_increment_by_value(metrics_collector):
    """Test incrementing by a specific value."""
    metrics, _ = metrics_collector
    metrics.increment("test_metric", 5)
    assert metrics.get("test_metric") == 5


def test_get_all_metrics(metrics_collector):
    """Test getting all metrics."""
    metrics, _ = metrics_collector
    metrics.increment("metric1")
    metrics.increment("metric2")

    all_metrics = metrics.get_all()
    assert len(all_metrics) == 2
    assert "metric1" in all_metrics
    assert "metric2" in all_metrics


def test_save_and_load_json(metrics_collector):
    """Test saving to JSON (metrics are per-session, NOT loaded on startup)."""
    metrics, temp_file_name = metrics_collector
    metrics.increment("test_metric", 10)

    metrics.force_save()

    with open(temp_file_name, 'r') as f:
        saved_data = json.load(f)
    assert saved_data["test_metric"] == 10

    metrics2 = MetricsCollector(Path(temp_file_name))
    assert metrics2.get("test_metric") == 0


def test_reset_all_metrics(metrics_collector):
    """Test resetting all metrics."""
    metrics, _ = metrics_collector
    metrics.increment("metric1")
    metrics.increment("metric2")

    metrics.reset()
    assert len(metrics.get_all()) == 0


def test_get_nonexistent_metric(metrics_collector):
    """Test getting nonexistent metric returns 0."""
    metrics, _ = metrics_collector
    value = metrics.get("nonexistent")
    assert value == 0


def test_increment_creates_metric(metrics_collector):
    """Test incrementing creates new metric if doesn't exist."""
    metrics, _ = metrics_collector
    metrics.increment("new_metric")
    assert metrics.get("new_metric") == 1


def test_persistence_after_reset(metrics_collector):
    """Test new MetricsCollector starts fresh (per-session behavior)."""
    metrics, temp_file_name = metrics_collector
    metrics.increment("test", 5)
    metrics.reset()

    metrics2 = MetricsCollector(Path(temp_file_name))
    assert len(metrics2.get_all()) == 0


def test_increment_large_value(metrics_collector):
    """Test incrementing by large value."""
    metrics, _ = metrics_collector
    metrics.increment("large", 1000000)
    assert metrics.get("large") == 1000000


def test_multiple_increments_same_metric(metrics_collector):
    """Test multiple increments accumulate correctly."""
    metrics, _ = metrics_collector
    for i in range(10):
        metrics.increment("counter")

    assert metrics.get("counter") == 10


def test_concurrent_metrics(metrics_collector):
    """Test tracking multiple different metrics."""
    metrics, _ = metrics_collector
    metrics.increment("messages_sent", 5)
    metrics.increment("messages_received", 3)
    metrics.increment("messages_queued", 2)

    assert metrics.get("messages_sent") == 5
    assert metrics.get("messages_received") == 3
    assert metrics.get("messages_queued") == 2


def test_set_metric(metrics_collector):
    """Test setting a metric to a specific value."""
    metrics, _ = metrics_collector
    metrics.set("seconds_ran", 100)
    assert metrics.get("seconds_ran") == 100

    metrics.set("seconds_ran", 50)
    assert metrics.get("seconds_ran") == 50


def test_set_vs_increment(metrics_collector):
    """Test that set replaces while increment adds."""
    metrics, _ = metrics_collector
    metrics.increment("counter", 10)
    assert metrics.get("counter") == 10
    metrics.increment("counter", 5)
    assert metrics.get("counter") == 15

    metrics.set("timer", 100)
    assert metrics.get("timer") == 100
    metrics.set("timer", 50)
    assert metrics.get("timer") == 50


def test_metrics_counters_after_flow(metrics_collector):
    """Test verify messages_received/sent incremented after message flow."""
    metrics, _ = metrics_collector
    metrics.increment("messages_received_telegram")
    metrics.increment("messages_sent_discord")
    metrics.increment("messages_sent_discord")

    assert metrics.get("messages_received_telegram") == 1
    assert metrics.get("messages_sent_discord") == 2


def test_metrics_ocr_processed_counter(metrics_collector):
    """Test OCR processed metric increments correctly."""
    metrics, _ = metrics_collector
    metrics.increment("ocr_processed")
    metrics.increment("ocr_processed")
    metrics.increment("ocr_processed")

    assert metrics.get("ocr_processed") == 3


def test_metrics_seconds_ran_timer(metrics_collector):
    """Test seconds_ran timer metric uses set (not increment)."""
    metrics, _ = metrics_collector
    metrics.set("seconds_ran", 100)
    assert metrics.get("seconds_ran") == 100

    metrics.set("seconds_ran", 200)
    assert metrics.get("seconds_ran") == 200
    assert metrics.get("seconds_ran") != 300


def test_reset_single_metric(metrics_collector):
    """Test resetting a single metric."""
    metrics, _ = metrics_collector
    metrics.increment("metric1", 10)
    metrics.increment("metric2", 20)

    metrics.reset_metric("metric1")

    assert metrics.get("metric1") == 0
    assert metrics.get("metric2") == 20


def test_reset_metric_nonexistent(metrics_collector):
    """Test resetting a metric that doesn't exist (should be no-op)."""
    metrics, _ = metrics_collector
    metrics.increment("existing", 5)

    metrics.reset_metric("nonexistent")

    assert metrics.get("existing") == 5


def test_save_metrics_write_error():
    """Test that save errors are handled gracefully."""
    bad_path = Path("/invalid/path/that/does/not/exist/metrics.json")
    metrics = MetricsCollector(bad_path)
    metrics.increment("test", 1)

    try:
        metrics.force_save()
    except Exception as e:
        pytest.fail(f"force_save raised an exception: {e}")


def test_periodic_save_triggers_after_interval(metrics_collector):
    """Test that _maybe_save_metrics saves after interval elapses."""
    _, temp_file_name = metrics_collector
    metrics = MetricsCollector(Path(temp_file_name))

    metrics.increment("test", 1)
    metrics._last_save_time = time.time() - (metrics.SAVE_INTERVAL + 1)
    metrics.increment("test2", 1)

    assert not metrics._dirty


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_ocr_msgs_sent_metric_incremented(mock_config_class, mock_telegram_client):
    """Test ocr_msgs_sent metric is incremented when OCR messages are sent."""
    from Watchtower import Watchtower
    import asyncio

    mock_config = Mock()
    mock_config.tmp_dir = Path(tempfile.mkdtemp())
    mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
    mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
    mock_config.telegramlog_dir = mock_config.tmp_dir / "telegramlog"
    mock_config.project_root = mock_config.tmp_dir
    mock_config.config_dir = mock_config.tmp_dir / "config"
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"
    mock_config.get_all_channel_ids = Mock(return_value=set())
    mock_config.destinations = []
    mock_config_class.return_value = mock_config

    temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_metrics.close()
    isolated_metrics = MetricsCollector(Path(temp_metrics.name))

    app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=False
    )
    message_data.ocr_raw = "Some OCR text"

    with patch.object(app.discord, 'send_message', return_value=True):
        destination = {
            'type': 'discord',
            'name': 'Test',
            'discord_webhook_url': 'http://test.com',
            'parser': {}
        }
        content = app.discord.format_message(message_data, destination)
        asyncio.run(app._send_to_discord(message_data, destination, content, False))

    assert app.metrics.get("ocr_msgs_sent") == 1

    os.unlink(temp_metrics.name)
    import shutil
    shutil.rmtree(mock_config.tmp_dir)


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_ocr_msgs_sent_not_incremented_without_ocr(mock_config_class, mock_telegram_client):
    """Test ocr_msgs_sent metric NOT incremented for non-OCR messages."""
    from Watchtower import Watchtower
    import asyncio

    mock_config = Mock()
    mock_config.tmp_dir = Path(tempfile.mkdtemp())
    mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
    mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
    mock_config.telegramlog_dir = mock_config.tmp_dir / "telegramlog"
    mock_config.project_root = mock_config.tmp_dir
    mock_config.config_dir = mock_config.tmp_dir / "config"
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"
    mock_config.get_all_channel_ids = Mock(return_value=set())
    mock_config.destinations = []
    mock_config_class.return_value = mock_config

    temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_metrics.close()
    isolated_metrics = MetricsCollector(Path(temp_metrics.name))

    app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=False
    )

    with patch.object(app.discord, 'send_message', return_value=True):
        destination = {
            'type': 'discord',
            'name': 'Test',
            'discord_webhook_url': 'http://test.com',
            'parser': {}
        }
        content = app.discord.format_message(message_data, destination)
        asyncio.run(app._send_to_discord(message_data, destination, content, False))

    assert app.metrics.get("ocr_msgs_sent") == 0

    os.unlink(temp_metrics.name)
    import shutil
    shutil.rmtree(mock_config.tmp_dir)


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_seconds_ran_metric_per_session(mock_config_class, mock_telegram_client):
    """Test seconds_ran metric is per-session, not cumulative."""
    from Watchtower import Watchtower
    import asyncio
    import time

    mock_config = Mock()
    mock_config.tmp_dir = Path(tempfile.mkdtemp())
    mock_config.attachments_dir = mock_config.tmp_dir / "attachments"
    mock_config.rsslog_dir = mock_config.tmp_dir / "rsslog"
    mock_config.telegramlog_dir = mock_config.tmp_dir / "telegramlog"
    mock_config.project_root = mock_config.tmp_dir
    mock_config.config_dir = mock_config.tmp_dir / "config"
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"
    mock_config.get_all_channel_ids = Mock(return_value=set())
    mock_config.destinations = []
    mock_config_class.return_value = mock_config

    temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_metrics.close()
    isolated_metrics = MetricsCollector(Path(temp_metrics.name))

    app1 = Watchtower(sources=[], metrics=isolated_metrics)
    app1.telegram.client.is_connected = lambda: False
    app1._start_time = time.time() - 10
    asyncio.run(app1.shutdown())

    first_seconds_ran = isolated_metrics.get("seconds_ran")
    assert first_seconds_ran >= 9
    assert first_seconds_ran <= 12

    app2 = Watchtower(sources=[], metrics=isolated_metrics)
    app2.telegram.client.is_connected = lambda: False
    app2._start_time = time.time() - 5
    asyncio.run(app2.shutdown())

    second_seconds_ran = isolated_metrics.get("seconds_ran")
    assert second_seconds_ran >= 4
    assert second_seconds_ran <= 7

    os.unlink(temp_metrics.name)
    import shutil
    shutil.rmtree(mock_config.tmp_dir)
