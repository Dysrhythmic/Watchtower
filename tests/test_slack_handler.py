"""Test SlackHandler - Slack webhook message delivery."""
import asyncio
import sys
import os
from unittest.mock import Mock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from SlackHandler import SlackHandler
from MessageData import MessageData
from datetime import datetime, timezone


@pytest.fixture
def handler():
    """Create SlackHandler instance."""
    return SlackHandler()


def test_inherits_destination_handler(handler):
    """Test that SlackHandler inherits from DestinationHandler."""
    assert isinstance(handler, DestinationHandler)


def test_file_size_limit_zero(handler):
    """Test that file size limit is zero (webhooks don't support files)."""
    assert handler.file_size_limit == 0


def test_format_message_slack_markdown(handler):
    """Test message formatting uses Slack markdown (single asterisk for bold)."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        text="Test message"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)
    assert "*New message from:*" in formatted
    assert "*By:*" in formatted
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
    assert "*Matched:*" in formatted
    assert "`CVE`" in formatted
    assert "`ransomware`" in formatted


@patch('requests.post')
def test_send_message_success(mock_post, handler):
    """Test successful message send."""
    mock_post.return_value.status_code = 200
    success = asyncio.run(handler.send_message("Test", "https://hooks.slack.com/services/test", None))
    assert success
    mock_post.assert_called_once()


@patch('requests.post')
def test_send_message_with_attachment_shows_warning(mock_post, handler):
    """Test that attachment path triggers warning message."""
    mock_post.return_value.status_code = 200

    success = asyncio.run(handler.send_message("Test message", "https://hooks.slack.com/services/test", "/tmp/test.jpg"))
    assert success

    # Check that the call included the attachment warning
    call_args = mock_post.call_args
    payload = call_args[1]['json']
    assert "*[attachments not supported by webhook]*" in payload['text']
    assert "Test message" in payload['text']


@patch('requests.post')
def test_handle_429_response_with_retry_after_header(mock_post, handler):
    """Test handling 429 rate limit response with Retry-After header."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers.get.return_value = '5'
    mock_post.return_value = mock_response

    success = asyncio.run(handler.send_message("Test", "https://hooks.slack.com/services/test", None))
    assert not success


@patch('requests.post')
def test_send_message_network_error(mock_post, handler):
    """Test handling network errors."""
    mock_post.side_effect = Exception("Network error")

    success = asyncio.run(handler.send_message("Test", "https://hooks.slack.com/services/test", None))
    assert not success


@patch('requests.post')
def test_send_message_500_error(mock_post, handler):
    """Test handling 500 server error."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_post.return_value = mock_response

    success = asyncio.run(handler.send_message("Test", "https://hooks.slack.com/services/test", None))
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
    """Test chunking sends multiple messages at 3000 char limit."""
    mock_post.return_value.status_code = 200

    long_text = "a" * 5000
    success = asyncio.run(handler.send_message(long_text, "https://hooks.slack.com/services/test", None))

    assert success
    assert mock_post.call_count > 1


@patch('requests.post')
def test_send_message_over_3000_char_chunked(mock_post):
    """Test message over 3000 chars is chunked."""
    handler = SlackHandler()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    text = "A" * 5000
    webhook_url = "https://hooks.slack.com/services/test"

    result = asyncio.run(handler.send_message(text, webhook_url, attachment_path=None))

    assert result
    assert mock_post.call_count >= 2

    for call in mock_post.call_args_list:
        if 'json' in call[1]:
            payload = call[1]['json']
            content = payload.get('text', '')
            assert len(content) <= 3000


@patch('requests.post')
def test_send_message_exactly_3000_char_no_chunking(mock_post):
    """Test message with exactly 3000 chars needs no chunking."""
    handler = SlackHandler()

    mock_response = Mock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    text = "A" * 3000
    webhook_url = "https://hooks.slack.com/services/test"

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

    assert "*  Replying to:*" in formatted
    assert "@originaluser" in formatted
    assert "2025-01-01 12:00:00 UTC" in formatted
    assert "*  Original message:*" in formatted
    assert "This is the original message being replied to" in formatted
    assert "This is a reply to the previous message" in formatted


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

    assert "*  Replying to:*" in formatted
    assert "@mediauser" in formatted
    assert "*  Original content:* Photo" in formatted
    assert "*  Original message:* [Attachment only, no caption]" in formatted


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


@patch('requests.post')
def test_extract_retry_after_from_header(mock_post, handler):
    """Test extraction of retry_after from Retry-After header."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {'Retry-After': '10'}
    mock_post.return_value = mock_response

    retry_after = handler._extract_retry_after(mock_response)
    assert retry_after == 10.0


@patch('requests.post')
def test_extract_retry_after_missing_header(mock_post, handler):
    """Test extraction falls back to 1.0 when header is missing."""
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_post.return_value = mock_response

    retry_after = handler._extract_retry_after(mock_response)
    assert retry_after == 1.0


@patch('requests.post')
def test_send_message_204_success(mock_post, handler):
    """Test that 204 status code is also considered success."""
    mock_post.return_value.status_code = 204
    success = asyncio.run(handler.send_message("Test", "https://hooks.slack.com/services/test", None))
    assert success


@patch('requests.post')
def test_rate_limit_prevents_send(mock_post, handler):
    """Test that rate limited webhook prevents message send."""
    # First call returns 429
    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_response_429.headers = {'Retry-After': '60'}

    # Second call should not happen due to rate limit
    mock_response_200 = Mock()
    mock_response_200.status_code = 200

    mock_post.side_effect = [mock_response_429, mock_response_200]

    webhook_url = "https://hooks.slack.com/services/test"

    # First send gets rate limited
    success1 = asyncio.run(handler.send_message("Test1", webhook_url, None))
    assert not success1

    # Second send should be blocked by rate limit check
    success2 = asyncio.run(handler.send_message("Test2", webhook_url, None))
    assert not success2

    # Only one POST should have been made (the first one that got 429)
    assert mock_post.call_count == 1


def test_format_message_with_ocr(handler):
    """Test formatting message with OCR text."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime.now(timezone.utc),
        text="Message with image",
        ocr_raw="OCR extracted text\nSecond line"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)

    assert "*OCR:*" in formatted
    assert "> OCR extracted text" in formatted
    assert "> Second line" in formatted


def test_format_message_with_attachment_type(handler):
    """Test formatting message with attachment type."""
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime.now(timezone.utc),
        text="",
        has_attachments=True,
        attachment_type="Photo"
    )
    dest = {'keywords': []}
    formatted = handler.format_message(msg, dest)

    assert "*Content:* Photo" in formatted
