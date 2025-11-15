"""Test DiscordHandler - Discord webhook message delivery."""
import asyncio
import sys
import os
from unittest.mock import Mock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from DiscordHandler import DiscordHandler
from MessageData import MessageData
from datetime import datetime, timezone


@pytest.fixture
def handler():
    """Create DiscordHandler instance."""
    return DiscordHandler()


def test_inherits_destination_handler(handler):
    """Test that DiscordHandler inherits from DestinationHandler."""
    assert isinstance(handler, DestinationHandler)


def test_format_message_markdown(handler):
    """Test message formatting uses markdown."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        text="Test message"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)
    assert "**New message from:**" in formatted
    assert "**By:**" in formatted
    assert "Test Channel" in formatted


def test_format_message_with_keywords(handler):
    """Test formatted message displays matched keywords."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Message"
    )
    dest = {'keywords': ['CVE', 'ransomware']}
    formatted = handler.format_message(msg, dest)
    assert "**Matched:**" in formatted
    assert "`CVE`" in formatted
    assert "`ransomware`" in formatted


@patch('requests.post')
def test_send_message_success(mock_post, handler):
    """Test successful message send."""
    mock_post.return_value.status_code = 200
    success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", None))
    assert success
    mock_post.assert_called_once()


@patch('requests.post')
def test_handle_429_response(mock_post, handler):
    """Test handling 429 rate limit response."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.json.return_value = {'retry_after': 5.5}
    mock_post.return_value = mock_response

    success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", None))
    assert not success


@patch('requests.post')
def test_send_message_with_media(mock_post, handler):
    """Test sending message with media attachment."""
    mock_post.return_value.status_code = 200

    with patch('builtins.open', create=True) as mock_file:
        mock_file.return_value.__enter__.return_value.read.return_value = b'fake image data'
        success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", "/tmp/test.jpg"))
        assert success


@patch('requests.post')
def test_send_message_network_error(mock_post, handler):
    """Test handling network errors."""
    mock_post.side_effect = Exception("Network error")

    success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", None))
    assert not success


@patch('requests.post')
def test_send_message_500_error(mock_post, handler):
    """Test handling 500 server error."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", None))
    assert not success


def test_format_message_includes_all_fields(handler):
    """Test formatted message includes all message fields."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Security News",
        username="@newsbot",
        timestamp=datetime.now(timezone.utc),
        text="Breaking news"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)

    assert "Security News" in formatted
    assert "@newsbot" in formatted
    assert "Breaking news" in formatted


@patch('requests.post')
def test_chunked_message_sends_multiple(mock_post, handler):
    """Test chunking sends multiple messages."""
    mock_post.return_value.status_code = 200

    long_text = "a" * 3000
    success = asyncio.run(handler.send_message(long_text, "https://discord.com/webhook", None))

    assert success
    assert mock_post.call_count > 1


@patch('requests.post')
def test_send_message_over_2000_char_chunked(mock_post):
    """Test message over 2000 chars is chunked."""
    handler = DiscordHandler()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    text = "A" * 3000
    webhook_url = "https://discord.com/api/webhooks/test"

    result = asyncio.run(handler.send_message(text, webhook_url, attachment_path=None))

    assert result
    assert mock_post.call_count >= 2

    for call in mock_post.call_args_list:
        if 'json' in call[1]:
            payload = call[1]['json']
            content = payload.get('content', '')
            assert len(content) <= 2000


@patch('requests.post')
def test_send_message_exactly_2000_char_no_chunking(mock_post):
    """Test message with exactly 2000 chars needs no chunking."""
    handler = DiscordHandler()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    text = "A" * 2000
    webhook_url = "https://discord.com/api/webhooks/test"

    result = asyncio.run(handler.send_message(text, webhook_url, attachment_path=None))

    assert result
    assert mock_post.call_count == 1


def test_format_message_with_reply_context(handler):
    """Test formatting message with reply context."""
    reply_context = {
        'message_id': 123,
        'author': '@originaluser',
        'text': 'This is the original message being replied to',
        'time': '2025-01-01 12:00:00 UTC',
        'attachment_type': None,
        'has_attachments': False
    }

    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@replyinguser",
        timestamp=datetime(2025, 1, 1, 12, 30, 0, tzinfo=timezone.utc),
        text="This is a reply to the previous message",
        reply_context=reply_context
    )

    dest = {'keywords': []}

    formatted = handler.format_message(msg, dest)

    assert "**  Replying to:**" in formatted
    assert "@originaluser" in formatted
    assert "2025-01-01 12:00:00 UTC" in formatted
    assert "**  Original message:**" in formatted
    assert "This is the original message being replied to" in formatted
    assert "This is a reply to the previous message" in formatted


@patch('requests.post')
def test_send_message_with_media_error(mock_post, handler):
    """Test handling of error response when sending media."""
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "Internal Server Error"

    with patch('builtins.open', create=True) as mock_file:
        with patch('os.path.exists', return_value=True):
            mock_file.return_value.__enter__.return_value.read.return_value = b'fake image data'
            success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", "/tmp/test.jpg"))
            assert not success


@patch('requests.post')
def test_send_message_with_media_rate_limit(mock_post, handler):
    """Test handling of rate limit (429) when sending media."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.json.return_value = {'retry_after': 5.0}
    mock_post.return_value = mock_response

    with patch('builtins.open', create=True) as mock_file:
        with patch('os.path.exists', return_value=True):
            mock_file.return_value.__enter__.return_value.read.return_value = b'fake image data'
            success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", "/tmp/test.jpg"))
            assert not success


@patch('requests.post')
def test_handle_rate_limit_json_parse_error(mock_post, handler):
    """Test handling of rate limit response with invalid JSON."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_post.return_value = mock_response

    success = asyncio.run(handler.send_message("Test", "https://discord.com/webhook", None))
    assert not success


def test_format_message_with_reply_context_media_only(handler):
    """Test formatting reply context when original message had only media."""
    reply_context = {
        'message_id': 456,
        'author': '@mediauser',
        'text': '',
        'time': '2025-01-01 13:00:00 UTC',
        'attachment_type': 'Photo',
        'has_attachments': True
    }

    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime(2025, 1, 1, 13, 30, 0, tzinfo=timezone.utc),
        text="Replying to a photo",
        reply_context=reply_context
    )

    formatted = handler.format_message(msg, {})

    assert "**  Replying to:**" in formatted
    assert "@mediauser" in formatted
    assert "**  Original content:** Photo" in formatted
    assert "**  Original message:** [Attachment only, no caption]" in formatted


def test_format_message_with_reply_context_long_text(handler):
    """Test that reply context truncates long original messages."""
    long_text = "A" * 250

    reply_context = {
        'message_id': 789,
        'author': '@longuser',
        'text': long_text,
        'time': '2025-01-01 14:00:00 UTC',
        'attachment_type': None,
        'has_attachments': False
    }

    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime(2025, 1, 1, 14, 30, 0, tzinfo=timezone.utc),
        text="Replying to long text",
        reply_context=reply_context
    )

    formatted = handler.format_message(msg, {})

    assert "A" * 200 + " ..." in formatted
    assert "A" * 250 not in formatted
