"""Test TelegramHandler - Telegram client operations and message handling."""
import sys
import os
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import pytest
import asyncio
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from TelegramHandler import TelegramHandler
from MessageData import MessageData
from datetime import datetime, timezone
from telethon.tl.types import MessageMediaDocument


@pytest.fixture
def handler():
    """Create TelegramHandler with mocked config."""
    mock_config = Mock()
    mock_config.project_root = Path("/tmp")
    mock_config.config_dir = Path("/tmp/config")
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"

    with patch('TelegramHandler.TelegramClient'):
        return TelegramHandler(mock_config)


@pytest.fixture
def mock_config():
    """Create mock config for tests."""
    config = Mock()
    config.api_id = "123456"
    config.api_hash = "test_hash"
    config.project_root = Path("/tmp/test")
    config.config_dir = config.project_root / "config"
    return config


@pytest.fixture
def log_handler():
    """Create TelegramHandler with temp log directory."""
    temp_dir = Path(tempfile.mkdtemp())
    telegramlog_dir = temp_dir / "telegramlog"
    telegramlog_dir.mkdir(parents=True, exist_ok=True)

    mock_config = Mock()
    mock_config.project_root = temp_dir
    mock_config.config_dir = temp_dir / "config"
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"
    mock_config.telegramlog_dir = telegramlog_dir
    mock_config.channel_names = {
        '-100123456789': 'Test Channel',
        '@testchannel': 'Test Username Channel',
        '987654321': 'Plain ID Channel'
    }

    with patch('TelegramHandler.TelegramClient'):
        handler = TelegramHandler(mock_config)

    yield handler, temp_dir, telegramlog_dir

    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def watchtower_cleanup():
    """Create Watchtower with temp directories for cleanup tests."""
    temp_dir = Path(tempfile.mkdtemp())
    telegramlog_dir = temp_dir / "telegramlog"
    telegramlog_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = temp_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    mock_config = Mock()
    mock_config.project_root = temp_dir
    mock_config.telegramlog_dir = telegramlog_dir
    mock_config.tmp_dir = temp_dir
    mock_config.attachments_dir = attachments_dir
    mock_config.destinations = []
    mock_config.rss_feeds = []

    from Watchtower import Watchtower
    watchtower = Watchtower(
        sources=[],
        config=mock_config,
        telegram=Mock(),
        discord=Mock(),
        router=Mock(),
        ocr=Mock(),
        message_queue=Mock(),
        metrics=Mock()
    )

    yield watchtower, temp_dir, telegramlog_dir, attachments_dir

    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def test_inherits_destination_handler(handler):
    """Test that TelegramHandler inherits from DestinationHandler."""
    assert isinstance(handler, DestinationHandler)


def test_format_message_html(handler):
    """Test message formatting uses HTML."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        text="Test message"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)
    assert "<b>New message from:</b>" in formatted
    assert "<b>By:</b>" in formatted


def test_defang_url(handler):
    """Test URL defanging."""
    url = "https://t.me/channel/123"
    defanged = handler._defang_tme(url)
    assert defanged == "hxxps://t[.]me/channel/123"


def test_build_message_url_public(handler):
    """Test building public channel URL."""
    url = handler.build_message_url("123", "@channel", 456)
    assert url == "https://t.me/channel/456"


def test_build_message_url_private(handler):
    """Test building private channel URL."""
    url = handler.build_message_url("-1001234567890", "Private", 456)
    assert url == "https://t.me/c/1234567890/456"


def test_restricted_mode_blocks_photo(handler):
    """Test restricted mode blocks photos."""
    from telethon.tl.types import MessageMediaPhoto

    mock_msg = Mock()
    mock_msg.media = MessageMediaPhoto()

    is_restricted = handler._is_attachment_restricted(mock_msg)
    assert is_restricted


def test_no_media_is_allowed(handler):
    """Test messages without media are allowed."""
    mock_msg = Mock()
    mock_msg.media = None

    is_restricted = handler._is_attachment_restricted(mock_msg)
    assert not is_restricted


def test_format_message_with_keywords(handler):
    """Test formatted message displays matched keywords."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Message"
    )
    dest = {'keywords': ['CVE', 'malware']}
    formatted = handler.format_message(msg, dest)
    assert "<b>Matched:</b>" in formatted
    assert "<code>CVE</code>" in formatted
    assert "<code>malware</code>" in formatted


def test_defang_multiple_protocols(handler):
    """Test defanging t.me URLs only."""
    urls = [
        ("https://t.me/chan/123", "hxxps://t[.]me/chan/123"),
        ("http://t.me/test", "hxxp://t[.]me/test"),
        ("https://telegram.me/chan", "hxxps://telegram[.]me/chan")
    ]
    for original, expected in urls:
        result = handler._defang_tme(original)
        assert result == expected


def test_build_message_url_numeric_public(handler):
    """Test building URL for numeric public channel."""
    url = handler.build_message_url("-1001234567890", "-1001234567890", 123)
    assert "t.me/c/" in url


def test_format_message_escapes_html(handler):
    """Test HTML characters are properly escaped."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test <script>",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="<b>Bold</b> & special chars"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)
    assert "&lt;" in formatted
    assert "&gt;" in formatted
    assert "&amp;" in formatted


@patch('TelegramHandler.TelegramClient')
def test_send_message_creates_client(mock_client, handler):
    """Test send_message uses Telegram client."""
    assert handler.client is not None


def test_caption_limit_constant(handler):
    """Test MAX_CAPTION_LENGTH constant is set correctly."""
    assert handler.MAX_CAPTION_LENGTH == 1024


def test_caption_length_validation_logic():
    """Test caption length validation logic."""
    assert TelegramHandler.MAX_CAPTION_LENGTH == 1024

    caption_ok = "x" * 1024
    caption_too_long = "y" * 1025

    assert len(caption_ok) <= TelegramHandler.MAX_CAPTION_LENGTH
    assert len(caption_too_long) > TelegramHandler.MAX_CAPTION_LENGTH


@patch('TelegramHandler.TelegramClient')
def test_send_message_text_only_under_4096(MockClient, mock_config):
    """Test text message under 4096 chars sends in single message."""
    handler = TelegramHandler(mock_config)
    handler.client.send_message = AsyncMock(return_value=Mock(id=123))

    text = "A" * 2000
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=text,
        attachment_path=None
    ))

    assert result
    handler.client.send_message.assert_called_once()
    call_args = handler.client.send_message.call_args
    assert call_args[0][0] == destination
    assert len(call_args[0][1]) == 2000


@patch('TelegramHandler.TelegramClient')
def test_send_message_text_over_4096_chunked(MockClient, mock_config):
    """Test text over 4096 chars is chunked."""
    handler = TelegramHandler(mock_config)
    handler.client.send_message = AsyncMock(return_value=Mock(id=123))

    text = "A" * 6000
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=text,
        attachment_path=None
    ))

    assert result
    assert handler.client.send_message.call_count == 2

    total_sent = sum(len(call[0][1]) for call in handler.client.send_message.call_args_list)
    assert total_sent > 5900
    assert total_sent < 6100


@patch('os.path.exists')
@patch('TelegramHandler.TelegramClient')
def test_send_message_media_with_caption_under_1024(MockClient, mock_exists, mock_config):
    """Test media with caption under 1024 chars."""
    handler = TelegramHandler(mock_config)
    handler.client.send_file = AsyncMock(return_value=Mock(id=123))
    handler.client.send_message = AsyncMock()

    attachment_path = "/tmp/test.jpg"
    mock_exists.return_value = True
    caption = "A" * 500
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=caption,
        attachment_path=attachment_path
    ))

    assert result
    handler.client.send_file.assert_called_once()
    call_args = handler.client.send_file.call_args
    assert call_args[0][0] == destination
    assert call_args[0][1] == attachment_path
    assert call_args[1].get('caption') is not None
    assert len(call_args[1]['caption']) == 500

    handler.client.send_message.assert_not_called()


@patch('os.path.exists')
@patch('TelegramHandler.TelegramClient')
def test_send_message_media_with_caption_over_1024_captionless_plus_chunks(MockClient, mock_exists, mock_config):
    """Test media with caption over 1024 chars sends captionless plus text."""
    handler = TelegramHandler(mock_config)
    handler.client.send_file = AsyncMock(return_value=Mock(id=123))
    handler.client.send_message = AsyncMock(return_value=Mock(id=124))

    attachment_path = "/tmp/test.jpg"
    mock_exists.return_value = True
    long_caption = "A" * 1500
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=long_caption,
        attachment_path=attachment_path
    ))

    assert result
    handler.client.send_file.assert_called_once()
    file_call_args = handler.client.send_file.call_args
    assert file_call_args[0][1] == attachment_path
    caption_arg = file_call_args[1].get('caption')
    assert caption_arg is None or caption_arg == ""

    handler.client.send_message.assert_called_once()
    message_call_args = handler.client.send_message.call_args
    sent_text = message_call_args[0][1]
    assert len(sent_text) == 1500
    assert sent_text == long_caption


@patch('os.path.exists')
@patch('TelegramHandler.TelegramClient')
def test_send_message_media_with_caption_over_5000_captionless_plus_chunked_text(MockClient, mock_exists, mock_config):
    """Test media with very long caption sends captionless plus chunked text."""
    handler = TelegramHandler(mock_config)
    handler.client.send_file = AsyncMock(return_value=Mock(id=123))
    handler.client.send_message = AsyncMock(return_value=Mock(id=124))

    attachment_path = "/tmp/test.jpg"
    mock_exists.return_value = True
    very_long_caption = "A" * 5500
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=very_long_caption,
        attachment_path=attachment_path
    ))

    assert result
    handler.client.send_file.assert_called_once()
    file_call_args = handler.client.send_file.call_args
    caption_arg = file_call_args[1].get('caption')
    assert caption_arg is None or caption_arg == ""

    assert handler.client.send_message.call_count == 2

    total_sent = sum(len(call[0][1]) for call in handler.client.send_message.call_args_list)
    assert total_sent > 5400
    assert total_sent < 5600


@patch('TelegramHandler.TelegramClient')
def test_send_message_flood_wait_error_enqueues(MockClient, mock_config):
    """Test FloodWaitError is caught and returns False."""
    from telethon.errors import FloodWaitError

    handler = TelegramHandler(mock_config)

    flood_error = FloodWaitError(request=Mock())
    flood_error.seconds = 60
    handler.client.send_message = AsyncMock(side_effect=flood_error)

    text = "Test message"
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=text,
        attachment_path=None
    ))

    assert not result


@patch('TelegramHandler.TelegramClient')
def test_send_message_generic_exception_enqueues(MockClient, mock_config):
    """Test generic exception is caught and returns False."""
    handler = TelegramHandler(mock_config)
    handler.client.send_message = AsyncMock(side_effect=Exception("Network error"))

    text = "Test message"
    destination = 123

    result = asyncio.run(handler.send_message(
        destination_chat_id=destination,
        content=text,
        attachment_path=None
    ))

    assert not result


@patch('TelegramHandler.TelegramClient')
def test_document_with_extension_and_mime_match_allowed(MockClient, mock_config):
    """Test document with matching extension and MIME is allowed."""
    handler = TelegramHandler(mock_config)

    message = Mock()
    message.media = Mock(spec=MessageMediaDocument)
    message.media.document = Mock()
    message.media.document.attributes = [
        Mock(file_name="data.csv", spec=['file_name'])
    ]
    message.media.document.mime_type = "text/csv"

    is_restricted = handler._is_attachment_restricted(message)

    assert not is_restricted


@patch('TelegramHandler.TelegramClient')
def test_document_with_extension_match_mime_mismatch_blocked(MockClient, mock_config):
    """Test document with extension match but MIME mismatch is blocked."""
    handler = TelegramHandler(mock_config)

    message = Mock()
    message.media = Mock(spec=MessageMediaDocument)
    message.media.document = Mock()
    message.media.document.attributes = [
        Mock(file_name="malware.csv", spec=['file_name'])
    ]
    message.media.document.mime_type = "application/x-msdownload"

    is_restricted = handler._is_attachment_restricted(message)

    assert is_restricted


@patch('TelegramHandler.TelegramClient')
def test_document_with_mime_match_extension_mismatch_blocked(MockClient, mock_config):
    """Test document with MIME match but extension mismatch is blocked."""
    handler = TelegramHandler(mock_config)

    message = Mock()
    message.media = Mock(spec=MessageMediaDocument)
    message.media.document = Mock()
    message.media.document.attributes = [
        Mock(file_name="data.exe", spec=['file_name'])
    ]
    message.media.document.mime_type = "text/csv"

    is_restricted = handler._is_attachment_restricted(message)

    assert is_restricted


@patch('TelegramHandler.TelegramClient')
def test_document_without_filename_attribute_blocked(MockClient, mock_config):
    """Test document without filename attribute is blocked."""
    handler = TelegramHandler(mock_config)

    message = Mock()
    message.media = Mock(spec=MessageMediaDocument)
    message.media.document = Mock()
    message.media.document.attributes = []
    message.media.document.mime_type = "text/csv"

    is_restricted = handler._is_attachment_restricted(message)

    assert is_restricted


@patch('TelegramHandler.TelegramClient')
def test_document_without_mime_type_blocked(MockClient, mock_config):
    """Test document without MIME type is blocked."""
    handler = TelegramHandler(mock_config)

    message = Mock()
    message.media = Mock(spec=MessageMediaDocument)
    message.media.document = Mock()
    message.media.document.attributes = [
        Mock(file_name="data.csv", spec=['file_name'])
    ]
    message.media.document.mime_type = None

    is_restricted = handler._is_attachment_restricted(message)

    assert is_restricted


@patch('TelegramHandler.TelegramClient')
def test_reply_context_success(MockClient, mock_config):
    """Test reply context extraction succeeds."""
    from telethon.tl.types import User

    handler = TelegramHandler(mock_config)

    mock_reply = Mock()
    mock_reply.id = 456
    mock_reply.text = "This is the original message"
    mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_reply.media = None

    mock_sender = Mock(spec=User)
    mock_sender.username = "replyuser"
    mock_sender.first_name = None
    mock_sender.last_name = None
    mock_reply.sender = mock_sender

    handler.client.get_messages = AsyncMock(return_value=mock_reply)

    mock_message = Mock()
    mock_message.chat_id = 123
    mock_message.reply_to = Mock()
    mock_message.reply_to.reply_to_msg_id = 456

    result = asyncio.run(handler._get_reply_context(mock_message))

    assert result is not None
    assert result['message_id'] == 456
    assert result['author'] == '@replyuser'
    assert result['text'] == 'This is the original message'
    assert result['time'] == '2025-01-01 12:00:00 UTC'
    assert not result['has_attachments']
    assert result['attachment_type'] is None


@patch('TelegramHandler.TelegramClient')
def test_reply_context_missing(MockClient, mock_config):
    """Test reply context returns None when message not found."""
    handler = TelegramHandler(mock_config)

    handler.client.get_messages = AsyncMock(return_value=None)

    mock_message = Mock()
    mock_message.chat_id = 123
    mock_message.reply_to = Mock()
    mock_message.reply_to.reply_to_msg_id = 999

    result = asyncio.run(handler._get_reply_context(mock_message))

    assert result is None


@patch('TelegramHandler.TelegramClient')
def test_reply_context_long_truncated(MockClient, mock_config):
    """Test reply context with long text is truncated in formatting."""
    from telethon.tl.types import User

    handler = TelegramHandler(mock_config)

    long_text = "A" * 250

    mock_reply = Mock()
    mock_reply.id = 456
    mock_reply.text = long_text
    mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_reply.media = None

    mock_sender = Mock(spec=User)
    mock_sender.username = "longuser"
    mock_sender.first_name = None
    mock_sender.last_name = None
    mock_reply.sender = mock_sender

    handler.client.get_messages = AsyncMock(return_value=mock_reply)

    mock_message = Mock()
    mock_message.chat_id = 123
    mock_message.reply_to = Mock()
    mock_message.reply_to.reply_to_msg_id = 456

    context = asyncio.run(handler._get_reply_context(mock_message))

    assert context is not None
    assert len(context['text']) == 250

    msg_data = MessageData(
        source_type="telegram",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="New message",
        reply_context=context
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg_data, dest)

    assert "A" * 200 in formatted
    assert "..." in formatted
    assert "A" * 250 not in formatted


@patch('TelegramHandler.TelegramClient')
def test_reply_context_malformed(MockClient, mock_config):
    """Test reply context handles malformed message gracefully."""
    from telethon.tl.types import User

    handler = TelegramHandler(mock_config)

    mock_reply = Mock()
    mock_reply.id = 456
    del mock_reply.text
    mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_reply.media = None

    mock_sender = Mock(spec=User)
    mock_sender.username = "malformeduser"
    mock_sender.first_name = None
    mock_sender.last_name = None
    mock_reply.sender = mock_sender

    type(mock_reply).text = property(lambda self: (_ for _ in ()).throw(AttributeError()))

    handler.client.get_messages = AsyncMock(return_value=mock_reply)

    mock_message = Mock()
    mock_message.chat_id = 123
    mock_message.reply_to = Mock()
    mock_message.reply_to.reply_to_msg_id = 456

    result = asyncio.run(handler._get_reply_context(mock_message))

    assert result is None


def test_telegram_log_path_numeric_id(log_handler):
    """Test log path strips -100 prefix from numeric IDs."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'

    log_path = handler._telegram_log_path(channel_id)

    assert log_path.name == '123456789.txt'
    assert log_path.parent == telegramlog_dir


def test_telegram_log_path_username_id(log_handler):
    """Test log path strips @ prefix from username IDs."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '@testchannel'

    log_path = handler._telegram_log_path(channel_id)

    assert log_path.name == 'testchannel.txt'
    assert log_path.parent == telegramlog_dir


def test_telegram_log_path_plain_id(log_handler):
    """Test log path handles plain numeric IDs."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '987654321'

    log_path = handler._telegram_log_path(channel_id)

    assert log_path.name == '987654321.txt'
    assert log_path.parent == telegramlog_dir


def test_create_telegram_log(log_handler):
    """Test creating telegram log with proper format."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'
    msg_id = 42

    handler._create_telegram_log(channel_id, msg_id)

    log_path = handler._telegram_log_path(channel_id)
    assert log_path.exists()

    content = log_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 2
    assert lines[0] == 'Test Channel'
    assert lines[1] == '42'


def test_create_telegram_log_unresolved_channel(log_handler):
    """Test creating log for unresolved channel."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100999999999'
    msg_id = 100

    handler._create_telegram_log(channel_id, msg_id)

    log_path = handler._telegram_log_path(channel_id)
    content = log_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert lines[0] == 'Unresolved:-100999999999'
    assert lines[1] == '100'


def test_read_telegram_log_existing(log_handler):
    """Test reading message ID from existing log."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'
    msg_id = 42
    handler._create_telegram_log(channel_id, msg_id)

    result = handler._read_telegram_log(channel_id)

    assert result == 42


def test_read_telegram_log_nonexistent(log_handler):
    """Test reading nonexistent log returns None."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100999999999'

    result = handler._read_telegram_log(channel_id)

    assert result is None


def test_read_telegram_log_corrupted(log_handler):
    """Test reading corrupted log handles error."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'
    log_path = handler._telegram_log_path(channel_id)
    log_path.write_text("Test Channel\ninvalid_number\n", encoding='utf-8')

    result = handler._read_telegram_log(channel_id)

    assert result is None


def test_read_telegram_log_single_line(log_handler):
    """Test reading single-line log returns None."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'
    log_path = handler._telegram_log_path(channel_id)
    log_path.write_text("Test Channel\n", encoding='utf-8')

    result = handler._read_telegram_log(channel_id)

    assert result is None


def test_update_telegram_log(log_handler):
    """Test updating existing telegram log."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'
    handler._create_telegram_log(channel_id, 42)

    handler._update_telegram_log(channel_id, 100)

    content = handler._telegram_log_path(channel_id).read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert lines[0] == 'Test Channel'
    assert lines[1] == '100'


def test_update_telegram_log_creates_if_missing(log_handler):
    """Test updating creates log if it doesn't exist."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '-100123456789'

    handler._update_telegram_log(channel_id, 50)

    log_path = handler._telegram_log_path(channel_id)
    assert log_path.exists()

    content = log_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert lines[1] == '50'


def test_telegram_log_workflow(log_handler):
    """Test complete workflow: create, read, update."""
    handler, temp_dir, telegramlog_dir = log_handler
    channel_id = '@testchannel'

    handler._create_telegram_log(channel_id, 1)

    assert handler._read_telegram_log(channel_id) == 1

    handler._update_telegram_log(channel_id, 2)

    assert handler._read_telegram_log(channel_id) == 2

    handler._update_telegram_log(channel_id, 100)

    assert handler._read_telegram_log(channel_id) == 100


def test_multiple_channel_logs(log_handler):
    """Test managing logs for multiple channels."""
    handler, temp_dir, telegramlog_dir = log_handler
    channels = {
        '-100123456789': 42,
        '@channel1': 100,
        '987654321': 200
    }

    for channel_id, msg_id in channels.items():
        handler._create_telegram_log(channel_id, msg_id)

    for channel_id, expected_msg_id in channels.items():
        assert handler._read_telegram_log(channel_id) == expected_msg_id

    handler._update_telegram_log('-100123456789', 500)

    assert handler._read_telegram_log('-100123456789') == 500
    assert handler._read_telegram_log('@channel1') == 100
    assert handler._read_telegram_log('987654321') == 200


def test_clear_telegram_logs(watchtower_cleanup):
    """Test clearing all telegram log files."""
    watchtower, temp_dir, telegramlog_dir, attachments_dir = watchtower_cleanup

    (telegramlog_dir / "123456789.txt").write_text("Channel 1\n100\n")
    (telegramlog_dir / "channel1.txt").write_text("Channel 2\n200\n")
    (telegramlog_dir / "999999999.txt").write_text("Channel 3\n300\n")

    watchtower._clear_telegram_logs()

    remaining_files = list(telegramlog_dir.glob("*.txt"))
    assert len(remaining_files) == 0


def test_clear_telegram_logs_empty_directory(watchtower_cleanup):
    """Test clearing empty directory."""
    watchtower, temp_dir, telegramlog_dir, attachments_dir = watchtower_cleanup

    watchtower._clear_telegram_logs()

    assert telegramlog_dir.exists()


def test_clear_telegram_logs_nonexistent_directory(watchtower_cleanup):
    """Test clearing nonexistent directory."""
    watchtower, temp_dir, telegramlog_dir, attachments_dir = watchtower_cleanup

    shutil.rmtree(telegramlog_dir)

    watchtower._clear_telegram_logs()

    assert not telegramlog_dir.exists()


def test_clear_telegram_logs_preserves_other_files(watchtower_cleanup):
    """Test clearing only removes .txt files."""
    watchtower, temp_dir, telegramlog_dir, attachments_dir = watchtower_cleanup

    (telegramlog_dir / "channel1.txt").write_text("Channel 1\n100\n")
    (telegramlog_dir / "README.md").write_text("# Telegram Logs")
    (telegramlog_dir / "data.json").write_text("{}")

    watchtower._clear_telegram_logs()

    assert not (telegramlog_dir / "channel1.txt").exists()
    assert (telegramlog_dir / "README.md").exists()
    assert (telegramlog_dir / "data.json").exists()


def test_extract_username_from_sender_user_with_names_no_username():
    """Test extracting username from User with first/last name but no username."""
    from telethon.tl.types import User

    user = Mock(spec=User)
    user.username = None
    user.first_name = "John"
    user.last_name = "Doe"

    result = TelegramHandler._extract_username_from_sender(user)
    assert result == "John Doe"


def test_extract_username_from_sender_user_first_name_only():
    """Test extracting username from User with only first name."""
    from telethon.tl.types import User

    user = Mock(spec=User)
    user.username = None
    user.first_name = "Alice"
    user.last_name = None

    result = TelegramHandler._extract_username_from_sender(user)
    assert result == "Alice"


def test_extract_username_from_sender_channel_without_username():
    """Test extracting username from Channel without username."""
    from telethon.tl.types import Channel

    channel = Mock(spec=Channel)
    channel.username = None

    result = TelegramHandler._extract_username_from_sender(channel)
    assert result == "Channel"


def test_get_attachment_type_other():
    """Test getting attachment type for unknown media."""
    unknown_media = Mock()
    result = TelegramHandler._get_attachment_type(unknown_media)
    assert result == "Other"


def test_build_message_url_no_message_id():
    """Test building URL returns None when message_id is None."""
    result = TelegramHandler.build_message_url("@channel", "@channel", None)
    assert result is None


def test_build_message_url_private_without_prefix():
    """Test building URL for channel ID without -100 prefix."""
    result = TelegramHandler.build_message_url("1234567890", None, 42)
    assert result == "https://t.me/c/1234567890/42"


def test_build_message_url_with_negative_sign():
    """Test building URL for channel ID with negative sign but no -100."""
    result = TelegramHandler.build_message_url("-1234567890", None, 42)
    assert result == "https://t.me/c/1234567890/42"


def test_build_defanged_tg_url_none_url():
    """Test building defanged URL returns None when URL is None."""
    result = TelegramHandler.build_defanged_tg_url("@channel", "@channel", None)
    assert result is None
