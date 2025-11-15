"""Tests for Watchtower async pipeline integration."""
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


@patch('Watchtower.os.path.exists')
@patch('MetricsCollector.MetricsCollector')
@patch('MessageQueue.MessageQueue')
@patch('DiscordHandler.DiscordHandler')
@patch('TelegramHandler.TelegramHandler')
@patch('OCRHandler.OCRHandler')
@patch('MessageRouter.MessageRouter')
@patch('ConfigManager.ConfigManager')
def test_ocr_trigger_when_enabled_for_channel(MockConfig, MockRouter, MockOCR, MockTelegram, MockDiscord, MockQueue, MockMetrics, mock_exists):
    """Test OCR extraction when enabled for channel."""
    from Watchtower import Watchtower

    mock_exists.return_value = True

    mock_config = MockConfig.return_value
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "hash"
    mock_config.telegram_session_name = "session"
    mock_config.project_root = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.tmp_dir = Path("/tmp")

    mock_router = MockRouter.return_value
    mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)

    mock_ocr = MockOCR.return_value
    mock_ocr.is_available = Mock(return_value=True)
    mock_ocr.extract_text = Mock(return_value="Extracted text from image")

    mock_telegram = MockTelegram.return_value
    mock_telegram.download_attachment = AsyncMock(return_value="/tmp/attachments/test.jpg")

    watchtower = Watchtower(sources=['telegram'])

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123456",
        channel_name="test_channel",
        username="test_user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=True,
        attachment_path=None
    )
    message_data.original_message = Mock()

    asyncio.run(watchtower._preprocess_message(message_data))

    mock_router.is_ocr_enabled_for_channel.assert_called_once()
    mock_ocr.extract_text.assert_called_once()
    assert message_data.ocr_enabled
    assert message_data.ocr_raw == "Extracted text from image"


@patch('MetricsCollector.MetricsCollector')
@patch('MessageQueue.MessageQueue')
@patch('DiscordHandler.DiscordHandler')
@patch('TelegramHandler.TelegramHandler')
@patch('OCRHandler.OCRHandler')
@patch('MessageRouter.MessageRouter')
@patch('ConfigManager.ConfigManager')
def test_ocr_skipped_when_not_enabled_for_channel(MockConfig, MockRouter, MockOCR, MockTelegram, MockDiscord, MockQueue, MockMetrics):
    """Test OCR extraction is skipped when not enabled."""
    from Watchtower import Watchtower

    mock_config = MockConfig.return_value
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "hash"
    mock_config.telegram_session_name = "session"
    mock_config.project_root = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.tmp_dir = Path("/tmp")

    mock_router = MockRouter.return_value
    mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

    mock_ocr = MockOCR.return_value
    mock_ocr.is_available = Mock(return_value=True)
    mock_ocr.extract_text = Mock()

    mock_telegram = MockTelegram.return_value

    watchtower = Watchtower(sources=['telegram'])

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123456",
        channel_name="test_channel",
        username="test_user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=True
    )
    message_data.original_message = Mock()

    asyncio.run(watchtower._preprocess_message(message_data))

    mock_ocr.extract_text.assert_not_called()
    assert not message_data.ocr_enabled


@patch('MetricsCollector.MetricsCollector')
@patch('MessageQueue.MessageQueue')
@patch('DiscordHandler.DiscordHandler')
@patch('OCRHandler.OCRHandler')
@patch('TelegramHandler.TelegramHandler')
@patch('MessageRouter.MessageRouter')
@patch('ConfigManager.ConfigManager')
def test_defanged_url_added_to_telegram_messages(MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
    """Test defanged URL is added to Telegram messages."""
    from Watchtower import Watchtower

    mock_config = MockConfig.return_value
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "hash"
    mock_config.telegram_session_name = "session"
    mock_config.project_root = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.tmp_dir = Path("/tmp")

    mock_router = MockRouter.return_value
    mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

    mock_telegram = MockTelegram.return_value
    mock_telegram.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/testchannel/123")

    watchtower = Watchtower(sources=['telegram'])

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123456",
        channel_name="testchannel",
        username="test_user",
        timestamp=datetime.now(timezone.utc),
        text="Test message"
    )
    message_data.original_message = Mock()
    message_data.original_message.id = 123

    asyncio.run(watchtower._preprocess_message(message_data))

    mock_telegram.build_defanged_tg_url.assert_called_once_with("123456", "testchannel", 123)
    assert 'src_url_defanged' in message_data.metadata
    assert message_data.metadata['src_url_defanged'] == "hxxps://t[.]me/testchannel/123"


@patch('MetricsCollector.MetricsCollector')
@patch('MessageQueue.MessageQueue')
@patch('DiscordHandler.DiscordHandler')
@patch('OCRHandler.OCRHandler')
@patch('TelegramHandler.TelegramHandler')
@patch('MessageRouter.MessageRouter')
@patch('ConfigManager.ConfigManager')
def test_media_restrictions_enforced_for_restricted_destinations(MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
    """Test media restrictions are enforced for restricted mode destinations."""
    from Watchtower import Watchtower

    mock_config = MockConfig.return_value
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "hash"
    mock_config.telegram_session_name = "session"
    mock_config.project_root = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.tmp_dir = Path("/tmp")

    mock_router = MockRouter.return_value

    mock_telegram = MockTelegram.return_value
    mock_telegram._is_attachment_restricted = Mock(return_value=False)
    mock_telegram.download_attachment = AsyncMock(return_value="/tmp/attachments/test.jpg")

    watchtower = Watchtower(sources=['telegram'])

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123456",
        channel_name="test_channel",
        username="test_user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=True
    )
    message_data.original_message = Mock()

    destinations = [
        {'type': 'Telegram', 'restricted_mode': True, 'telegram_dst_channel': '@channel'}
    ]

    result = asyncio.run(watchtower._handle_attachment_restrictions(message_data, destinations))

    mock_telegram._is_attachment_restricted.assert_called_once()
    assert result


@patch('MetricsCollector.MetricsCollector')
@patch('MessageQueue.MessageQueue')
@patch('DiscordHandler.DiscordHandler')
@patch('OCRHandler.OCRHandler')
@patch('TelegramHandler.TelegramHandler')
@patch('MessageRouter.MessageRouter')
@patch('ConfigManager.ConfigManager')
def test_media_blocked_when_restricted_mode_fails(MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
    """Test media is blocked when restricted mode check fails."""
    from Watchtower import Watchtower

    mock_config = MockConfig.return_value
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "hash"
    mock_config.telegram_session_name = "session"
    mock_config.project_root = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.tmp_dir = Path("/tmp")

    mock_router = MockRouter.return_value

    mock_telegram = MockTelegram.return_value
    mock_telegram._is_attachment_restricted = Mock(return_value=True)
    mock_telegram.download_attachment = AsyncMock(return_value="/tmp/attachments/test.jpg")

    watchtower = Watchtower(sources=['telegram'])

    message_data = MessageData(
        source_type="Telegram",
        channel_id="123456",
        channel_name="test_channel",
        username="test_user",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        has_attachments=True
    )
    message_data.original_message = Mock()

    destinations = [
        {'type': 'Telegram', 'restricted_mode': True, 'telegram_dst_channel': '@channel'}
    ]

    result = asyncio.run(watchtower._handle_attachment_restrictions(message_data, destinations))

    assert not result
