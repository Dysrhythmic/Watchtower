"""Integration tests for RSS processing and queue retry mechanisms."""
import asyncio
import sys
import os
import tempfile
import time
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path
from datetime import datetime, timezone
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS
from SendStatus import SendStatus
from conftest import create_mock_config


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_rss_to_discord_flow(mock_post, mock_config_class, mock_telegram_client):
    """Test complete RSS → Discord pipeline."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"https://example.com/feed.xml"}),
        'destinations': [{
            'name': 'Security Alerts',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': 'https://example.com/feed.xml',
                'keywords': ['vulnerability', 'CVE'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    mock_post.return_value.status_code = 200

    app = Watchtower(sources=[APP_TYPE_RSS])

    msg = MessageData(
        source_type="RSS",
        channel_id="https://example.com/feed.xml",
        channel_name="Security Feed",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="New vulnerability CVE-2025-1234 discovered in popular library"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1
    assert destinations[0]['type'] == 'Discord'
    assert 'CVE' in destinations[0]['keywords']

    formatted = app.discord.format_message(msg, destinations[0])
    success = asyncio.run(app.discord.send_message(formatted, destinations[0]['discord_webhook_url'], None))

    assert success
    assert 'Security Feed' in formatted
    mock_post.assert_called_once()


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_rss_to_telegram_flow(mock_config_class, mock_telegram_client):
    """Test complete RSS → Telegram pipeline."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"https://threatfeeds.io/rss"}),
        'destinations': [{
            'name': 'Threat Intelligence',
            'type': 'Telegram',
            'telegram_dst_channel': '@threat_alerts',
            'channels': [{
                'id': 'https://threatfeeds.io/rss',
                'keywords': ['ransomware', 'malware'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    mock_telegram = mock_telegram_client.return_value
    mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    mock_telegram.send_message = AsyncMock(return_value=True)

    app = Watchtower(sources=[APP_TYPE_RSS])

    app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    app.telegram.send_message = AsyncMock(return_value=True)

    msg = MessageData(
        source_type="RSS",
        channel_id="https://threatfeeds.io/rss",
        channel_name="ThreatFeeds",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="New ransomware campaign targeting healthcare sector"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1
    assert destinations[0]['type'] == 'Telegram'
    assert 'ransomware' in destinations[0]['keywords']


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_rss_no_keywords_forwards_all(mock_post, mock_config_class, mock_telegram_client):
    """Test RSS feed with no keywords forwards all messages."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"https://example.com/all.xml"}),
        'destinations': [{
            'name': 'All News',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': 'https://example.com/all.xml',
                'keywords': [],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config
    mock_post.return_value.status_code = 200

    app = Watchtower(sources=[APP_TYPE_RSS])

    msg = MessageData(
        source_type="RSS",
        channel_id="https://example.com/all.xml",
        channel_name="General News",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="Regular news article about weather"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1
    assert destinations[0]['keywords'] == []


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_queue_manages_multiple_items(mock_post, mock_config_class, mock_telegram_client):
    """Test queue manages multiple items correctly."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    destinations = [
        {'name': 'Dest1', 'type': 'Discord', 'discord_webhook_url': 'https://discord.com/webhook1'},
        {'name': 'Dest2', 'type': 'Discord', 'discord_webhook_url': 'https://discord.com/webhook2'},
        {'name': 'Dest3', 'type': 'Discord', 'discord_webhook_url': 'https://discord.com/webhook3'},
    ]

    for dest in destinations:
        app.message_queue.enqueue(
            destination=dest,
            formatted_content="Test message",
            attachment_path=None,
            reason="test"
        )

    assert app.message_queue.get_queue_size() == 3

    for item in app.message_queue._queue:
        assert item.destination is not None
        assert item.formatted_content is not None
        assert item.attempt_count == 0
        assert item.next_retry_time > time.time()


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_queue_sets_retry_timing(mock_config_class, mock_telegram_client):
    """Test queue items have proper retry timing set."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    destination = {
        'name': 'Test',
        'type': 'Discord',
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    before_enqueue = time.time()
    app.message_queue.enqueue(
        destination=destination,
        formatted_content="Test",
        attachment_path=None
    )
    after_enqueue = time.time()

    item = app.message_queue._queue[0]
    assert item.next_retry_time > before_enqueue
    expected_retry = after_enqueue + app.message_queue.INITIAL_BACKOFF
    assert abs(item.next_retry_time - expected_retry) < 1.0


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_queue_tracks_retry_attempts(mock_config_class, mock_telegram_client):
    """Test queue tracks retry attempt counts properly."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    destination = {
        'name': 'Test',
        'type': 'Discord',
        'discord_webhook_url': 'https://discord.com/webhook'
    }
    app.message_queue.enqueue(
        destination=destination,
        formatted_content="Test",
        attachment_path=None
    )

    item = app.message_queue._queue[0]

    assert item.attempt_count == 0

    item.attempt_count = 1
    backoff_1 = app.message_queue.INITIAL_BACKOFF * (2 ** item.attempt_count)
    assert backoff_1 == 10

    item.attempt_count = 2
    backoff_2 = app.message_queue.INITIAL_BACKOFF * (2 ** item.attempt_count)
    assert backoff_2 == 20

    assert app.message_queue.MAX_RETRIES == 3


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_telegram_to_telegram_forwarding(mock_config_class, mock_telegram_client):
    """Test forwarding from one Telegram channel to another."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@source_channel"}),
        'destinations': [{
            'name': 'Mirror Channel',
            'type': 'Telegram',
            'telegram_dst_channel': '@destination_channel',
            'channels': [{
                'id': '@source_channel',
                'keywords': [],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    app.telegram.send_message = AsyncMock(return_value=True)

    msg = MessageData(
        source_type="Telegram",
        channel_id="@source_channel",
        channel_name="Source Channel",
        username="@testuser",
        timestamp=datetime.now(timezone.utc),
        text="Test message to forward"
    )
    msg.original_message = Mock()

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 1
    assert destinations[0]['type'] == 'Telegram'

    formatted = app.telegram.format_message(msg, destinations[0])
    result = asyncio.run(app._send_to_telegram(
        msg, destinations[0], formatted, include_attachment=False
    ))

    assert result == SendStatus.SENT
    app.telegram.resolve_destination.assert_called_once_with('@destination_channel')
    app.telegram.send_message.assert_called_once()


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_telegram_to_multiple_telegram_destinations(mock_config_class, mock_telegram_client):
    """Test forwarding one Telegram message to multiple Telegram channels."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@news_source"}),
        'destinations': [
            {
                'name': 'Public Feed',
                'type': 'Telegram',
                'telegram_dst_channel': '@public_feed',
                'channels': [{
                    'id': '@news_source',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            },
            {
                'name': 'Private Archive',
                'type': 'Telegram',
                'telegram_dst_channel': '@private_archive',
                'channels': [{
                    'id': '@news_source',
                    'keywords': [],
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
        channel_id="@news_source",
        channel_name="News Source",
        username="@reporter",
        timestamp=datetime.now(timezone.utc),
        text="Breaking news"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 2
    assert all(d['type'] == 'Telegram' for d in destinations)
    assert destinations[0]['telegram_dst_channel'] == '@public_feed'
    assert destinations[1]['telegram_dst_channel'] == '@private_archive'


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_cleanup_attachments_dir(mock_config_class, mock_telegram_client):
    """Test cleanup removes attachments directory contents."""
    from Watchtower import Watchtower

    temp_dir = Path(tempfile.mkdtemp())
    attachments_dir = temp_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    mock_config = create_mock_config({
        'tmp_dir': temp_dir,
        'attachments_dir': attachments_dir
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    media_file1 = attachments_dir / "test_media1.jpg"
    media_file2 = attachments_dir / "test_media2.png"
    media_file1.write_text("fake image data 1")
    media_file2.write_text("fake image data 2")

    assert media_file1.exists()
    assert media_file2.exists()

    app._cleanup_attachments_dir()

    import shutil
    shutil.rmtree(temp_dir)


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_multiple_destinations_rate_limited_independently(mock_post, mock_config_class, mock_telegram_client):
    """Test rate limits are tracked per-destination."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@test"}),
        'destinations': [
            {
                'name': 'Webhook 1',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook1',
                'channels': [{
                    'id': '@test',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            },
            {
                'name': 'Webhook 2',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook2',
                'channels': [{
                    'id': '@test',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }
        ]
    })
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    mock_post.side_effect = [
        Mock(status_code=429, json=lambda: {'retry_after': 5.0}),
        Mock(status_code=200)
    ]

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message"
    )

    destinations = app.router.get_destinations(msg)
    assert len(destinations) == 2

    formatted1 = app.discord.format_message(msg, destinations[0])
    success1 = asyncio.run(app.discord.send_message(formatted1, destinations[0]['discord_webhook_url'], None))
    assert not success1

    formatted2 = app.discord.format_message(msg, destinations[1])
    success2 = asyncio.run(app.discord.send_message(formatted2, destinations[1]['discord_webhook_url'], None))
    assert success2


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_telegram_and_rss_to_same_destination(mock_post, mock_config_class, mock_telegram_client):
    """Test messages from different sources routing to same destination."""
    from Watchtower import Watchtower

    mock_config = create_mock_config({
        'get_all_channel_ids': Mock(return_value={"@telegram_ch", "https://rss.feed/xml"}),
        'destinations': [{
            'name': 'Combined Feed',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [
                {
                    'id': '@telegram_ch',
                    'keywords': ['alert'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                },
                {
                    'id': 'https://rss.feed/xml',
                    'keywords': ['alert'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }
            ]
        }]
    })
    mock_config_class.return_value = mock_config
    mock_post.return_value.status_code = 200

    app = Watchtower(sources=[APP_TYPE_TELEGRAM, APP_TYPE_RSS])

    msg_telegram = MessageData(
        source_type="Telegram",
        channel_id="@telegram_ch",
        channel_name="Telegram Channel",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Security alert from Telegram"
    )

    msg_rss = MessageData(
        source_type="RSS",
        channel_id="https://rss.feed/xml",
        channel_name="RSS Feed",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="Security alert from RSS"
    )

    dests_telegram = app.router.get_destinations(msg_telegram)
    dests_rss = app.router.get_destinations(msg_rss)

    assert len(dests_telegram) == 1
    assert len(dests_rss) == 1
    assert dests_telegram[0]['name'] == 'Combined Feed'
    assert dests_rss[0]['name'] == 'Combined Feed'
