"""
Refactored tests for TelegramHandler and DiscordHandler.

This consolidates test_telegram_handler.py (1293 lines) and test_discord_handler.py (412 lines)
into a single, well-organized file using pytest fixtures (~400 lines total).

Tests cover:
- Message formatting (HTML for Telegram, Markdown for Discord)
- Send operations with success/failure handling
- Caption overflow handling
- Restricted mode for media filtering
- Reply context formatting
- Rate limit handling
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument


# ============================================================================
# TELEGRAM HANDLER TESTS
# ============================================================================

class TestTelegramHandler:
    """Tests for TelegramHandler operations."""

    def test_format_message_html(self, mock_telegram_handler, message_factory):
        """Test message formatting uses HTML markup."""
        msg = message_factory()
        dest = {'keywords': []}
        formatted = mock_telegram_handler.format_message(msg, dest)
        assert "<b>New message from:</b>" in formatted
        assert "<b>By:</b>" in formatted

    def test_format_message_with_keywords(self, mock_telegram_handler, message_factory):
        """Test formatted message displays matched keywords."""
        msg = message_factory()
        dest = {'keywords': ['CVE', 'malware']}
        formatted = mock_telegram_handler.format_message(msg, dest)
        assert "<b>Matched:</b>" in formatted
        assert "<code>CVE</code>" in formatted
        assert "<code>malware</code>" in formatted

    def test_defang_url(self, mock_telegram_handler):
        """Test URL defanging."""
        url = "https://t.me/channel/123"
        defanged = mock_telegram_handler._defang_tme(url)
        assert defanged == "hxxps://t[.]me/channel/123"

    def test_build_message_url_public(self, mock_telegram_handler):
        """Test building public channel URL."""
        url = mock_telegram_handler.build_message_url("123", "@channel", 456)
        assert url == "https://t.me/channel/456"

    def test_build_message_url_private(self, mock_telegram_handler):
        """Test building private channel URL."""
        url = mock_telegram_handler.build_message_url("-1001234567890", "Private", 456)
        assert url == "https://t.me/c/1234567890/456"

    def test_restricted_mode_blocks_photo(self, mock_telegram_handler, mock_telegram_message):
        """Test restricted mode blocks photos."""
        mock_msg = mock_telegram_message(has_attachments=True, attachment_type="photo")
        is_restricted = mock_telegram_handler._is_attachment_restricted(mock_msg)
        assert is_restricted is True

    def test_no_media_is_allowed(self, mock_telegram_handler, mock_telegram_message):
        """Test messages without media are allowed."""
        mock_msg = mock_telegram_message(has_attachments=False)
        is_restricted = mock_telegram_handler._is_attachment_restricted(mock_msg)
        assert is_restricted is False

    @pytest.mark.parametrize("caption_length,expected_calls", [
        (500, 1),    # Under 1024 limit - single send_file with caption
        (1500, 2),   # Over 1024 limit - send_file + send_message
        (5500, 3),   # Way over limit - send_file + chunked messages
    ])
    @patch('os.path.exists', return_value=True)
    def test_send_copy_caption_handling(self, mock_exists, mock_telegram_handler,
                                        caption_length, expected_calls):
        """
        Test caption overflow handling for various lengths.

        Tests: src/TelegramHandler.py:371-384 (caption overflow logic)
        """
        # Setup
        mock_telegram_handler.client.send_file = AsyncMock(return_value=Mock(id=123))
        mock_telegram_handler.client.send_message = AsyncMock(return_value=Mock(id=124))

        # Test data
        attachment_path = "/tmp/test.jpg"
        caption = "A" * caption_length
        destination = 123

        # When: send_copy() called
        result = asyncio.run(mock_telegram_handler.send_copy(
            destination_chat_id=destination,
            content=caption,
            attachment_path=attachment_path
        ))

        # Then: Appropriate number of calls made
        assert result is True
        total_calls = (mock_telegram_handler.client.send_file.call_count +
                      mock_telegram_handler.client.send_message.call_count)
        assert total_calls >= expected_calls

    def test_send_copy_text_only_under_4096(self, mock_telegram_handler):
        """Test sending text under Telegram's 4096 character limit."""
        mock_telegram_handler.client.send_message = AsyncMock(return_value=Mock(id=123))

        text = "A" * 2000  # Under 4096 limit
        result = asyncio.run(mock_telegram_handler.send_copy(
            destination_chat_id=123,
            content=text,
            attachment_path=None
        ))

        assert result is True
        mock_telegram_handler.client.send_message.assert_called_once()

    def test_send_copy_text_over_4096_chunked(self, mock_telegram_handler):
        """Test text chunking for messages over 4096 chars."""
        mock_telegram_handler.client.send_message = AsyncMock(return_value=Mock(id=123))

        text = "A" * 6000  # Over 4096 limit
        result = asyncio.run(mock_telegram_handler.send_copy(
            destination_chat_id=123,
            content=text,
            attachment_path=None
        ))

        assert result is True
        assert mock_telegram_handler.client.send_message.call_count >= 2

    def test_send_copy_flood_wait_error(self, mock_telegram_handler):
        """Test handling of FloodWaitError."""
        from telethon.errors import FloodWaitError

        flood_error = FloodWaitError(request=Mock())
        flood_error.seconds = 60
        mock_telegram_handler.client.send_message = AsyncMock(side_effect=flood_error)

        result = asyncio.run(mock_telegram_handler.send_copy(
            destination_chat_id=123,
            content="Test",
            attachment_path=None
        ))

        assert result is False


class TestTelegramReplyContext:
    """Tests for Telegram reply context handling."""

    def test_reply_context_success(self, mock_telegram_handler):
        """Test successful reply context extraction."""
        from telethon.tl.types import User

        # Mock the reply message
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

        mock_telegram_handler.client.get_messages = AsyncMock(return_value=mock_reply)

        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 456

        # When: Get reply context
        result = asyncio.run(mock_telegram_handler._get_reply_context(mock_message))

        # Then: Returns complete context
        assert result is not None
        assert result['message_id'] == 456
        assert result['author'] == '@replyuser'
        assert result['text'] == 'This is the original message'
        assert result['has_attachments'] is False

    def test_reply_context_missing(self, mock_telegram_handler):
        """Test handling of missing reply message."""
        mock_telegram_handler.client.get_messages = AsyncMock(return_value=None)

        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 999

        result = asyncio.run(mock_telegram_handler._get_reply_context(mock_message))
        assert result is None


class TestTelegramRestrictedMode:
    """Tests for restricted mode document validation (security-critical)."""

    def test_document_with_extension_and_mime_match_allowed(self, mock_telegram_handler):
        """Test that documents with matching extension and MIME are allowed."""
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [Mock(file_name="data.csv", spec=['file_name'])]
        message.media.document.mime_type = "text/csv"

        is_restricted = mock_telegram_handler._is_attachment_restricted(message)
        assert is_restricted is False

    def test_document_with_extension_match_mime_mismatch_blocked(self, mock_telegram_handler):
        """
        SECURITY TEST: Prevents malware disguised with safe extension.
        Extension matches but MIME type is malicious - should be blocked.
        """
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [Mock(file_name="malware.csv", spec=['file_name'])]
        message.media.document.mime_type = "application/x-msdownload"  # Executable!

        is_restricted = mock_telegram_handler._is_attachment_restricted(message)
        assert is_restricted is True

    def test_document_with_mime_match_extension_mismatch_blocked(self, mock_telegram_handler):
        """
        SECURITY TEST: Prevents executable files even with safe MIME.
        MIME matches but extension is malicious - should be blocked.
        """
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [Mock(file_name="data.exe", spec=['file_name'])]
        message.media.document.mime_type = "text/csv"

        is_restricted = mock_telegram_handler._is_attachment_restricted(message)
        assert is_restricted is True


# ============================================================================
# DISCORD HANDLER TESTS
# ============================================================================

class TestDiscordHandler:
    """Tests for DiscordHandler operations."""

    def test_format_message_markdown(self, mock_discord_handler, message_factory):
        """Test message formatting uses markdown."""
        msg = message_factory()
        dest = {'keywords': []}
        formatted = mock_discord_handler.format_message(msg, dest)
        assert "**New message from:**" in formatted
        assert "**By:**" in formatted

    def test_format_message_with_keywords(self, mock_discord_handler, message_factory):
        """Test formatted message displays matched keywords."""
        msg = message_factory()
        dest = {'keywords': ['CVE', 'ransomware']}
        formatted = mock_discord_handler.format_message(msg, dest)
        assert "**Matched:**" in formatted
        assert "`CVE`" in formatted
        assert "`ransomware`" in formatted

    @patch('requests.post')
    def test_send_message_success(self, mock_post, mock_discord_handler):
        """Test successful message send."""
        mock_post.return_value.status_code = 200
        success = mock_discord_handler.send_message("Test", "https://discord.com/webhook", None)
        assert success is True
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_handle_429_response(self, mock_post, mock_discord_handler):
        """Test handling 429 rate limit response."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {'retry_after': 5.5}
        mock_post.return_value = mock_response

        success = mock_discord_handler.send_message("Test", "https://discord.com/webhook", None)
        assert success is False

    @patch('requests.post')
    def test_send_message_over_2000_char_chunked(self, mock_post, mock_discord_handler):
        """
        Test Discord message chunking at 2000-char limit.

        Tests: src/DiscordHandler.py:42-75 (Discord chunking)
        CRITICAL: Discord has 2000-char limit vs Telegram's 4096.
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # Text over 2000 chars
        text = "A" * 3000
        result = mock_discord_handler.send_message(text, "https://discord.com/webhook", None)

        assert result is True
        assert mock_post.call_count >= 2

        # Verify each chunk is under 2000 chars
        for call in mock_post.call_args_list:
            if 'json' in call[1]:
                payload = call[1]['json']
                content = payload.get('content', '')
                assert len(content) <= 2000

    @patch('requests.post')
    def test_send_message_exactly_2000_char_no_chunking(self, mock_post, mock_discord_handler):
        """Test that exactly 2000 chars doesn't trigger chunking."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        text = "A" * 2000  # Exactly at limit
        result = mock_discord_handler.send_message(text, "https://discord.com/webhook", None)

        assert result is True
        assert mock_post.call_count == 1


class TestDiscordReplyContext:
    """Tests for Discord reply context formatting."""

    def test_format_message_with_reply_context(self, mock_discord_handler, message_factory):
        """Test that reply context is properly formatted in Discord messages."""
        reply_context = {
            'message_id': 123,
            'author': '@originaluser',
            'text': 'This is the original message being replied to',
            'time': '2025-01-01 12:00:00 UTC',
            'attachment_type': None,
            'has_attachments': False
        }

        msg = message_factory(
            text="This is a reply to the previous message",
            reply_context=reply_context
        )
        dest = {'keywords': []}

        formatted = mock_discord_handler.format_message(msg, dest)

        assert "**  Replying to:**" in formatted
        assert "@originaluser" in formatted
        assert "2025-01-01 12:00:00 UTC" in formatted
        assert "**  Original message:**" in formatted
        assert "This is the original message being replied to" in formatted

    def test_format_message_with_reply_context_long_text(self, mock_discord_handler,
                                                          message_factory):
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

        msg = message_factory(text="Replying to long text", reply_context=reply_context)
        formatted = mock_discord_handler.format_message(msg, {})

        # Should truncate at 200 chars and add " ..."
        assert "A" * 200 + " ..." in formatted
        assert "A" * 250 not in formatted


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
