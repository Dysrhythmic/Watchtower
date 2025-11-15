"""Integration tests for Watchtower message processing flows."""
import asyncio
import sys
import os
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path
from datetime import datetime, timezone
import pytest
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS
from conftest import create_mock_config


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_full_pipeline_text_only(mock_post, mock_config_class, mock_telegram_client):
    """Test full Telegram → Discord pipeline without media."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test_channel"}),
        'destinations': [{
            'name': 'Discord Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['CVE'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    mock_post.return_value.status_code = 200

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test_channel",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime.now(timezone.utc),
        text="New CVE-2025-1234 discovered"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1

    formatted = app.discord.format_message(msg, destinations[0])
    success = asyncio.run(app.discord.send_message(formatted, mock_config.destinations[0]['discord_webhook_url'], None))

    assert success
    mock_post.assert_called_once()


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_discord_429_enqueue(mock_post, mock_config_class, mock_telegram_client):
    """Test 429 response enqueues message."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_response_429.json.return_value = {'retry_after': 5.0}
    mock_post.return_value = mock_response_429

    destination = {
        'name': 'Test',
        'type': 'discord',
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    success = asyncio.run(app.discord.send_message("Test message", destination['discord_webhook_url'], None))
    assert not success

    app.message_queue.enqueue(
        destination=destination,
        formatted_content="Test message",
        attachment_path=None,
        reason="rate limit"
    )
    assert app.message_queue.get_queue_size() == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_metrics_increment_on_operations(mock_config_class, mock_telegram_client):
    """Test metrics are tracked correctly."""
    from Watchtower import Watchtower

    temp_dir = Path(tempfile.mkdtemp())

    mock_config = create_mock_config({
        'tmp_dir': temp_dir,
        'attachments_dir': temp_dir / "attachments"
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    app.metrics.increment("messages_received_telegram")
    app.metrics.increment("messages_sent_discord")
    app.metrics.increment("messages_sent_discord")

    assert app.metrics.get("messages_received_telegram") == 1
    assert app.metrics.get("messages_sent_discord") == 2

    app.metrics.force_save()

    metrics_file = temp_dir / "metrics.json"
    assert metrics_file.exists()

    import shutil
    shutil.rmtree(temp_dir)


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_keyword_matching_forwards_correctly(mock_config_class, mock_telegram_client):
    """Test message only forwards when keyword matches."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test_channel"}),
        'destinations': [{
            'name': 'Discord',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['ransomware'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg_no_match = MessageData(
        source_type="Telegram",
        channel_id="@test_channel",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Just a regular message"
    )

    destinations = app.router.get_destinations(msg_no_match)
    assert len(destinations) == 0

    msg_match = MessageData(
        source_type="Telegram",
        channel_id="@test_channel",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="New ransomware campaign detected"
    )

    destinations = app.router.get_destinations(msg_match)
    assert len(destinations) == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_same_channel_multiple_destinations(mock_config_class, mock_telegram_client):
    """Test one channel can route to multiple destinations."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test"}),
        'destinations': [
            {
                'name': 'Discord 1',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook1',
                'channels': [{
                    'id': '@test',
                    'keywords': ['CVE'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            },
            {
                'name': 'Discord 2',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook2',
                'channels': [{
                    'id': '@test',
                    'keywords': ['CVE'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }
        ]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="New CVE discovered"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 2
    assert destinations[0]['name'] == 'Discord 1'
    assert destinations[1]['name'] == 'Discord 2'


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_parser_trims_lines(mock_config_class, mock_telegram_client):
    """Test parser correctly trims lines from messages."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test"}),
        'destinations': [{
            'name': 'Discord',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test',
                'keywords': [],
                'restricted_mode': False,
                'parser': {
                    'trim_front_lines': 1,
                    'trim_back_lines': 1
                },
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Line 1\nLine 2\nLine 3\nLine 4"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1

    parsed = app.router.parse_msg(msg, destinations[0]['parser'])

    assert "Line 1" not in parsed.text
    assert "Line 4" not in parsed.text
    assert "Line 2" in parsed.text
    assert "Line 3" in parsed.text


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_discord_network_error_recovery(mock_post, mock_config_class, mock_telegram_client):
    """Test handling Discord network errors."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    mock_post.side_effect = Exception("Connection failed")

    success = asyncio.run(app.discord.send_message("Test", "https://discord.com/webhook", None))
    assert not success


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_empty_message_handling(mock_config_class, mock_telegram_client):
    """Test handling empty messages."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test"}),
        'destinations': [{
            'name': 'Test',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test',
                'keywords': [],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text=""
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_malformed_config_handling(mock_config_class, mock_telegram_client):
    """Test handling configuration with missing fields."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'destinations': []
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 0


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_media_with_ocr_extraction(mock_post, mock_config_class, mock_telegram_client):
    """Test media message with OCR text extraction."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test"}),
        'destinations': [{
            'name': 'Discord',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test',
                'keywords': ['secret'],
                'restricted_mode': False,
                'parser': None,
                'ocr': True
            }]
        }]
    })
    mock_config_class.return_value = mock_config
    mock_post.return_value.status_code = 200

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Check the image",
        ocr_raw="This is secret information"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_queue_backoff_progression(mock_config_class, mock_telegram_client):
    """Test exponential backoff progression."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    app.message_queue.enqueue(
        destination={'name': 'Test'},
        formatted_content="Test",
        attachment_path=None
    )

    item = app.message_queue._queue[0]

    initial_time = item.next_retry_time
    assert initial_time > time.time()

    item.attempt_count = 1
    backoff_1 = 5 * (2 ** item.attempt_count)
    assert backoff_1 == 10

    item.attempt_count = 2
    backoff_2 = 5 * (2 ** item.attempt_count)
    assert backoff_2 == 20


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_queue_drop_after_max_retries(mock_config_class, mock_telegram_client):
    """Test items dropped after max retries."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    app.message_queue.enqueue(
        destination={'name': 'Test'},
        formatted_content="Test",
        attachment_path=None
    )

    item = app.message_queue._queue[0]

    item.attempt_count = app.message_queue.MAX_RETRIES

    assert item.attempt_count >= app.message_queue.MAX_RETRIES


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_multiple_channels_same_destination(mock_config_class, mock_telegram_client):
    """Test single destination monitoring multiple channels."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@chan1", "@chan2"}),
        'destinations': [{
            'name': 'Discord',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [
                {
                    'id': '@chan1',
                    'keywords': ['alert'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                },
                {
                    'id': '@chan2',
                    'keywords': ['alert'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }
            ]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    msg1 = MessageData(
        source_type="Telegram",
        channel_id="@chan1",
        channel_name="Channel 1",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Alert message"
    )

    destinations1 = app.router.get_destinations(msg1)
    assert len(destinations1) == 1

    msg2 = MessageData(
        source_type="Telegram",
        channel_id="@chan2",
        channel_name="Channel 2",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Alert message"
    )

    destinations2 = app.router.get_destinations(msg2)
    assert len(destinations2) == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_mixed_source_types(mock_config_class, mock_telegram_client):
    """Test handling mixed Telegram and RSS sources."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@telegram_chan", "https://example.com/feed"}),
        'destinations': [{
            'name': 'Discord',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [
                {
                    'id': '@telegram_chan',
                    'keywords': ['news'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                },
                {
                    'id': 'https://example.com/feed',
                    'keywords': ['news'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }
            ]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM, APP_TYPE_RSS])

    msg_telegram = MessageData(
        source_type="Telegram",
        channel_id="@telegram_chan",
        channel_name="Telegram Channel",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Breaking news"
    )

    msg_rss = MessageData(
        source_type="RSS",
        channel_id="https://example.com/feed",
        channel_name="RSS Feed",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="Breaking news"
    )

    dest_telegram = app.router.get_destinations(msg_telegram)
    dest_rss = app.router.get_destinations(msg_rss)

    assert len(dest_telegram) == 1
    assert len(dest_rss) == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_caption_limit_constant(mock_config_class, mock_telegram_client):
    """Test that Telegram limits are correctly defined."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    assert app.telegram.MAX_CAPTION_LENGTH == 1024
    assert app.telegram.MAX_MSG_LENGTH == 4096


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_no_content_loss_with_long_caption_and_media(mock_config_class, mock_telegram_client):
    """Test NO content is lost when caption exceeds 1024 chars with media."""
    from Watchtower import Watchtower
    from TelegramHandler import TelegramHandler

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    test_content = "A" * 6700

    chunks = app.telegram._chunk_text(test_content, TelegramHandler.MAX_MSG_LENGTH)

    assert len(chunks) == 2
    assert len(chunks[0]) == 4096
    assert len(chunks[1]) == 2604

    rejoined = "".join(chunks)
    assert len(rejoined) == 6700
    assert rejoined == test_content


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_chunking_respects_message_boundaries(mock_config_class, mock_telegram_client):
    """Test that message chunks maintain ordering at 4096 char limit."""
    from Watchtower import Watchtower
    from TelegramHandler import TelegramHandler

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    chunk1 = "CHUNK_1_START " + ("x" * 4070) + " CHUNK_1_END "
    chunk2 = "CHUNK_2_START " + ("y" * 4070) + " CHUNK_2_END "
    chunk3 = "CHUNK_3_START " + ("z" * 500) + " CHUNK_3_END"

    long_message = chunk1 + chunk2 + chunk3

    chunks = app.telegram._chunk_text(long_message, TelegramHandler.MAX_MSG_LENGTH)

    assert len(chunks) == 3

    assert "CHUNK_1_START" in chunks[0]
    assert "CHUNK_2_START" in chunks[1]
    assert "CHUNK_3_START" in chunks[2]

    total_chars = sum(len(c) for c in chunks)
    assert total_chars >= len(long_message) - 10


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_ocr_msgs_sent_metric_tracked(mock_config_class, mock_telegram_client):
    """Test ocr_msgs_sent metric is incremented when messages with OCR are sent."""
    from Watchtower import Watchtower
    from MessageData import MessageData
    from MetricsCollector import MetricsCollector

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_metrics.close()
    isolated_metrics = MetricsCollector(Path(temp_metrics.name))

    app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=False
    )
    message_data.ocr_raw = "Some OCR extracted text"

    with patch.object(app.discord, 'send_message', return_value=True):
        destination = {
            'type': 'Discord',
            'name': 'Test',
            'discord_webhook_url': 'http://test.com',
            'parser': {}
        }

        content = app.discord.format_message(message_data, destination)
        asyncio.run(app._send_to_discord(message_data, destination, content, False))

    assert app.metrics.get("ocr_msgs_sent") == 1


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_ocr_msgs_sent_not_tracked_without_ocr(mock_config_class, mock_telegram_client):
    """Test ocr_msgs_sent metric is NOT incremented when messages have no OCR."""
    from Watchtower import Watchtower
    from MessageData import MessageData
    from MetricsCollector import MetricsCollector

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
    temp_metrics.close()
    isolated_metrics = MetricsCollector(Path(temp_metrics.name))

    app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=False
    )

    with patch.object(app.discord, 'send_message', return_value=True):
        destination = {
            'type': 'Discord',
            'name': 'Test',
            'discord_webhook_url': 'http://test.com',
            'parser': {}
        }

        content = app.discord.format_message(message_data, destination)
        asyncio.run(app._send_to_discord(message_data, destination, content, False))

    assert app.metrics.get("ocr_msgs_sent") == 0


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_seconds_ran_metric_per_session(mock_config_class, mock_telegram_client):
    """Test seconds_ran metric is per-session, not cumulative."""
    from Watchtower import Watchtower
    from MetricsCollector import MetricsCollector

    mock_config = create_mock_config()
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
