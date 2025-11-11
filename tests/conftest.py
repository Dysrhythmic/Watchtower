"""
Pytest configuration and shared fixtures for Watchtower tests.

This module provides reusable fixtures and factory functions to eliminate
code duplication across test files.
"""
import pytest
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS


# ============================================================================
# CONFIGURATION FIXTURES
# ============================================================================

@pytest.fixture
def mock_config():
    """Create a standard mock configuration object."""
    config = Mock()
    config.telegram_api_id = "123456"
    config.telegram_api_hash = "test_hash"
    config.telegram_session_name = "session"
    config.project_root = Path("/tmp/test")
    config.config_dir = Path("/tmp/test/config")
    config.attachments_dir = Path("/tmp/test/attachments")
    config.rsslog_dir = Path("/tmp/test/rsslog")
    config.telegramlog_dir = Path("/tmp/test/telegramlog")
    config.tmp_dir = Path("/tmp/test")
    config.destinations = []
    config.rss_feeds = []
    config.channel_names = {}
    return config


@pytest.fixture
def mock_destinations():
    """Create standard mock destinations configuration."""
    return [{
        'name': 'Test Discord',
        'type': 'Discord',
        'discord_webhook_url': 'https://discord.com/api/webhooks/test/token',
        'channels': [{
            'id': '@test_channel',
            'keywords': ['cve', 'malware'],
            'restricted_mode': False,
            'parser': None,
            'ocr': False
        }],
        'parser': {'trim_front_lines': 0, 'trim_back_lines': 0},
        'keywords': []
    }]


# ============================================================================
# HANDLER FIXTURES
# ============================================================================

@pytest.fixture
def mock_telegram_handler(mock_config):
    """Create a mocked TelegramHandler."""
    with patch('TelegramHandler.TelegramClient'):
        from TelegramHandler import TelegramHandler
        handler = TelegramHandler(mock_config)
        handler.client = Mock()
        handler.client.is_connected = Mock(return_value=False)
        handler.client.send_message = AsyncMock(return_value=Mock(id=123))
        handler.client.send_file = AsyncMock(return_value=Mock(id=124))
        handler.client.get_messages = AsyncMock(return_value=None)
        handler.download_attachment = AsyncMock(return_value="/tmp/test.jpg")
        handler.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/test/1")
        return handler


@pytest.fixture
def mock_discord_handler():
    """Create a real DiscordHandler instance for testing DiscordHandler methods.

    This fixture does NOT mock any methods, so tests can verify real behavior
    with mocked HTTP calls (via @patch('requests.post')).

    For Watchtower integration tests that need mocked handlers, use mock_discord_for_watchtower.
    """
    from DiscordHandler import DiscordHandler
    return DiscordHandler()


@pytest.fixture
def mock_discord_for_watchtower():
    """Create a heavily mocked DiscordHandler for Watchtower integration tests.

    This mocks send_message and format_message for integration tests.
    """
    handler = Mock()
    handler.send_message = Mock(return_value=True)
    handler.format_message = Mock(return_value="Formatted message")
    return handler


@pytest.fixture
def mock_message_router(mock_config):
    """Create a mocked MessageRouter."""
    from MessageRouter import MessageRouter
    router = MessageRouter(mock_config)
    router.parse_msg = Mock(side_effect=lambda msg, parser: msg)
    router.is_ocr_enabled_for_channel = Mock(return_value=False)
    router.is_channel_restricted = Mock(return_value=False)
    return router


@pytest.fixture
def mock_ocr_handler():
    """Create a mocked OCRHandler."""
    ocr = Mock()
    ocr.is_available = Mock(return_value=True)
    ocr.extract_text = Mock(return_value="OCR extracted text")
    return ocr


@pytest.fixture
def mock_message_queue():
    """Create a mocked MessageQueue."""
    from MessageQueue import MessageQueue
    queue = MessageQueue()
    queue.enqueue = Mock()
    queue.get_queue_size = Mock(return_value=0)
    return queue


@pytest.fixture
def mock_metrics():
    """Create a mocked MetricsCollector."""
    metrics = Mock()
    metrics.increment = Mock()
    metrics.get_metrics = Mock(return_value={})
    return metrics


# ============================================================================
# WATCHTOWER FIXTURES
# ============================================================================

@pytest.fixture
def mock_watchtower(mock_config, mock_telegram_handler, mock_discord_for_watchtower,
                    mock_message_router, mock_ocr_handler, mock_message_queue,
                    mock_metrics):
    """Create a fully-mocked Watchtower instance."""
    from Watchtower import Watchtower

    watchtower = Watchtower(
        sources=[APP_TYPE_TELEGRAM],
        config=mock_config,
        telegram=mock_telegram_handler,
        discord=mock_discord_for_watchtower,
        router=mock_message_router,
        ocr=mock_ocr_handler,
        message_queue=mock_message_queue,
        metrics=mock_metrics
    )
    return watchtower


# ============================================================================
# DATA FACTORY FUNCTIONS
# ============================================================================

@pytest.fixture
def message_factory():
    """Factory function to create MessageData instances."""
    def _create_message(
        source_type="Telegram",
        channel_id="@test_channel",
        channel_name="Test Channel",
        username="@testuser",
        text="Test message",
        has_attachments=False,
        attachment_type=None,
        attachment_path=None,
        ocr_raw=None,
        ocr_enabled=False,
        timestamp=None,
        reply_context=None,
        metadata=None
    ):
        """Create a MessageData instance with sensible defaults."""
        msg = MessageData(
            source_type=source_type,
            channel_id=channel_id,
            channel_name=channel_name,
            username=username,
            timestamp=timestamp or datetime.now(timezone.utc),
            text=text,
            has_attachments=has_attachments,
            attachment_type=attachment_type,
            attachment_path=attachment_path,
            ocr_raw=ocr_raw,
            ocr_enabled=ocr_enabled,
            reply_context=reply_context
        )
        if metadata:
            msg.metadata = metadata
        return msg

    return _create_message


@pytest.fixture
def destination_factory():
    """Factory function to create destination configurations."""
    def _create_destination(
        dest_type="Discord",
        name="Test Destination",
        webhook_url="https://discord.com/api/webhooks/test/token",
        telegram_channel=None,
        keywords=None,
        restricted_mode=False,
        parser=None,
        ocr_enabled=False
    ):
        """Create a destination configuration with sensible defaults."""
        dest = {
            'name': name,
            'type': dest_type,
            'keywords': keywords or [],
            'restricted_mode': restricted_mode,
            'parser': parser or {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        if dest_type == "Discord":
            dest['discord_webhook_url'] = webhook_url
        elif dest_type == "Telegram":
            dest['telegram_dst_channel'] = telegram_channel or '@test_destination'

        return dest

    return _create_destination


@pytest.fixture
def mock_telegram_message():
    """Factory for creating mock Telegram message objects."""
    def _create_telegram_message(
        message_id=1,
        text="Test message",
        has_attachments=False,
        attachment_type=None
    ):
        """Create a mock Telegram message object."""
        msg = Mock()
        msg.id = message_id
        msg.text = text
        msg.media = None

        if has_attachments:
            if attachment_type == "photo":
                from telethon.tl.types import MessageMediaPhoto
                msg.media = MessageMediaPhoto()
            elif attachment_type == "document":
                from telethon.tl.types import MessageMediaDocument
                msg.media = MessageMediaDocument()
                msg.media.document = Mock()
                msg.media.document.attributes = []
                msg.media.document.mime_type = "application/octet-stream"

        return msg

    return _create_telegram_message


# ============================================================================
# TEMPFILE FIXTURES FOR TESTING FILE OPERATIONS
# ============================================================================

@pytest.fixture
def temp_text_file():
    """Create a temporary text file for testing."""
    import tempfile
    def _create_temp_file(content="Test content", suffix='.txt'):
        """Create a temp file with given content and suffix."""
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
            f.write(content)
            return f.name
    return _create_temp_file


@pytest.fixture
def temp_binary_file():
    """Create a temporary binary file for testing."""
    import tempfile
    def _create_temp_file(content=b"Binary content", suffix='.bin'):
        """Create a temp binary file with given content and suffix."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as f:
            f.write(content)
            return f.name
    return _create_temp_file


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_mock_config(extra_attrs=None):
    """Helper to create properly configured mock config for integration tests.

    This function is used by integration tests that use unittest.TestCase style.
    For pytest tests, use the mock_config fixture instead.

    Args:
        extra_attrs: Optional dict of extra attributes to set on the mock config

    Returns:
        Mock config object with standard test configuration
    """
    mock_config = Mock()
    mock_config.tmp_dir = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.telegramlog_dir = Path("/tmp/telegramlog")
    mock_config.project_root = Path("/tmp")
    mock_config.config_dir = Path("/tmp/config")
    mock_config.telegram_api_id = "123"
    mock_config.telegram_api_hash = "abc"
    mock_config.telegram_session_name = "session"
    mock_config.get_all_channel_ids = Mock(return_value=set())
    mock_config.destinations = []
    mock_config.rss_feeds = []
    mock_config.channel_names = {}

    if extra_attrs:
        for key, value in extra_attrs.items():
            setattr(mock_config, key, value)

    return mock_config


def assert_message_sent(mock_handler, expected_calls=1):
    """Assert that a handler's send method was called the expected number of times."""
    if hasattr(mock_handler, 'send_message'):
        assert mock_handler.send_message.call_count == expected_calls
    elif hasattr(mock_handler, 'send_copy'):
        assert mock_handler.send_copy.call_count == expected_calls


def assert_metrics_incremented(mock_metrics, metric_name, expected_times=1):
    """Assert that a specific metric was incremented."""
    calls = [call for call in mock_metrics.increment.call_args_list
             if call[0][0] == metric_name]
    assert len(calls) == expected_times, \
        f"Expected metric '{metric_name}' to be incremented {expected_times} times, " \
        f"but was called {len(calls)} times"


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
