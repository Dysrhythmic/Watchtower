"""
Test DiscordHandler - Discord webhook message delivery

This module tests the DiscordHandler component which formats and sends
messages to Discord webhooks using markdown formatting.

What This Tests:
    - Message formatting (markdown bold, italic, code blocks, blockquotes)
    - Keyword display in formatted messages
    - Reply context formatting
    - OCR text formatting (blockquote style)
    - HTTP request construction for Discord API
    - Rate limit detection (429 responses)
    - Media attachment handling
    - Chunking for 2000-character Discord limit

Test Pattern - Message Formatting:
    1. Create MessageData with various content (text, OCR, reply context)
    2. Create destination dict with keywords
    3. Call handler.format_message(msg, destination)
    4. Assert output contains expected markdown formatting
    5. Check for **bold**, *italic*, `code`, and > blockquotes

Test Pattern - Sending:
    1. Mock requests.post to return success/failure responses
    2. Call handler.send_message(content, webhook_url, media_path)
    3. Check requests.post was called with correct parameters
    4. For rate limit tests: return Mock response with status_code=429

Mock Setup Template:
    msg = MessageData(
        source_type="telegram",
        channel_name="Test Channel",
        username="@testuser",
        timestamp=datetime.now(timezone.utc),
        text="Test message",
        ocr_raw="OCR text here"  # optional
    )

    destination = {
        'name': 'Test Dest',
        'keywords': ['keyword1', 'keyword2']
    }

    formatted = handler.format_message(msg, destination)

How to Add New Tests:
    1. Add test method starting with test_
    2. Use descriptive docstring: """Test <what Discord feature>."""
    3. Create MessageData with relevant content
    4. For formatting tests: assert string contains expected markdown
    5. For sending tests: use @patch('requests.post')
    6. For rate limit tests: mock 429 response with retry_after header
    7. Use self.assertIn/assertEqual for verification
"""
import unittest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from DiscordHandler import DiscordHandler
from MessageData import MessageData
from datetime import datetime, timezone


class TestDiscordHandler(unittest.TestCase):
    """Test DiscordHandler Discord webhook delivery and formatting."""

    def setUp(self):
        """Create DiscordHandler instance."""
        self.handler = DiscordHandler()

    def test_inherits_destination_handler(self):
        """Test that DiscordHandler inherits from DestinationHandler."""
        self.assertIsInstance(self.handler, DestinationHandler)

    def test_format_message_markdown(self):
        """Test message formatting uses markdown."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Test Channel",
            username="@testuser",
            timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            text="Test message"
        )
        dest = {'keywords': []}
        formatted = self.handler.format_message(msg, dest)
        self.assertIn("**New message from:**", formatted)
        self.assertIn("**By:**", formatted)
        self.assertIn("Test Channel", formatted)

    def test_format_message_with_keywords(self):
        """Test formatted message displays matched keywords."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Message"
        )
        dest = {'keywords': ['CVE', 'ransomware']}
        formatted = self.handler.format_message(msg, dest)
        self.assertIn("**Matched:**", formatted)
        self.assertIn("`CVE`", formatted)
        self.assertIn("`ransomware`", formatted)

    @patch('requests.post')
    def test_send_message_success(self, mock_post):
        """Test successful message send."""
        mock_post.return_value.status_code = 200
        success = self.handler.send_message("Test", "https://discord.com/webhook", None)
        self.assertTrue(success)
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_handle_429_response(self, mock_post):
        """Test handling 429 rate limit response."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {'retry_after': 5.5}
        mock_post.return_value = mock_response

        success = self.handler.send_message("Test", "https://discord.com/webhook", None)
        self.assertFalse(success)

    @patch('requests.post')
    def test_send_message_with_media(self, mock_post):
        """Test sending message with media attachment."""
        mock_post.return_value.status_code = 200

        with patch('builtins.open', create=True) as mock_file:
            mock_file.return_value.__enter__.return_value.read.return_value = b'fake image data'
            success = self.handler.send_message("Test", "https://discord.com/webhook", "/tmp/test.jpg")
            self.assertTrue(success)

    @patch('requests.post')
    def test_send_message_network_error(self, mock_post):
        """Test handling network errors."""
        mock_post.side_effect = Exception("Network error")

        success = self.handler.send_message("Test", "https://discord.com/webhook", None)
        self.assertFalse(success)

    @patch('requests.post')
    def test_send_message_500_error(self, mock_post):
        """Test handling 500 server error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        success = self.handler.send_message("Test", "https://discord.com/webhook", None)
        self.assertFalse(success)

    def test_format_message_includes_all_fields(self):
        """Test formatted message includes all message fields."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Security News",
            username="@newsbot",
            timestamp=datetime.now(timezone.utc),
            text="Breaking news"
        )
        dest = {'keywords': []}
        formatted = self.handler.format_message(msg, dest)

        self.assertIn("Security News", formatted)
        self.assertIn("@newsbot", formatted)
        self.assertIn("Breaking news", formatted)

    @patch('requests.post')
    def test_chunked_message_sends_multiple(self, mock_post):
        """Test chunking sends multiple messages."""
        mock_post.return_value.status_code = 200

        # Create message longer than 2000 chars
        long_text = "a" * 3000
        success = self.handler.send_message(long_text, "https://discord.com/webhook", None)

        # Should succeed and call post multiple times
        self.assertTrue(success)
        self.assertGreater(mock_post.call_count, 1)


class TestDiscordChunking(unittest.TestCase):
    """Tests for Discord message chunking at 2000-char limit."""

    @patch('requests.post')
    def test_send_message_over_2000_char_chunked(self, mock_post):
        """
        Given: Message with 3000 chars, no media
        When: send_message() called
        Then: Multiple webhook POSTs with chunked text at 2000-char limit

        Tests: src/DiscordHandler.py:42-75 (Discord chunking)

        This is CRITICAL - Discord has 2000-char limit vs Telegram's 4096.
        """
        from DiscordHandler import DiscordHandler

        # Given: Handler
        handler = DiscordHandler()

        # Mock successful responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # Test data
        text = "A" * 3000  # Over 2000 limit
        webhook_url = "https://discord.com/api/webhooks/test"

        # When: send_message() called
        result = handler.send_message(text, webhook_url, media_path=None)

        # Then: Success
        self.assertTrue(result)

        # Should call requests.post at least twice (2000 + 1000 chars)
        self.assertGreaterEqual(mock_post.call_count, 2)

        # Verify each chunk is under 2000 chars
        for call in mock_post.call_args_list:
            if 'json' in call[1]:  # Text-only chunks
                payload = call[1]['json']
                content = payload.get('content', '')
                self.assertLessEqual(len(content), 2000)

    @patch('requests.post')
    def test_send_message_exactly_2000_char_no_chunking(self, mock_post):
        """
        Given: Message with exactly 2000 chars
        When: send_message() called
        Then: Single webhook POST (no chunking needed)

        Tests: src/DiscordHandler.py:42 (chunking decision)
        """
        from DiscordHandler import DiscordHandler

        handler = DiscordHandler()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        text = "A" * 2000  # Exactly at limit
        webhook_url = "https://discord.com/api/webhooks/test"

        result = handler.send_message(text, webhook_url, media_path=None)

        # Should succeed with single POST
        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 1)


class TestDiscordReplyContext(unittest.TestCase):
    """Tests for Discord reply context formatting."""

    def setUp(self):
        """Create DiscordHandler instance."""
        self.handler = DiscordHandler()

    def test_format_message_with_reply_context(self):
        """
        Given: MessageData with reply_context
        When: format_message() called
        Then: Formatted message includes reply info with author, time, and original text

        Tests: src/DiscordHandler.py:110-111, 123-140 (reply context formatting)
        """
        from datetime import datetime, timezone

        # Create reply context
        reply_context = {
            'message_id': 123,
            'author': '@originaluser',
            'text': 'This is the original message being replied to',
            'time': '2025-01-01 12:00:00 UTC',
            'media_type': None,
            'has_media': False
        }

        # Create message with reply context
        msg = MessageData(
            source_type="telegram",
            channel_name="Test Channel",
            username="@replyinguser",
            timestamp=datetime(2025, 1, 1, 12, 30, 0, tzinfo=timezone.utc),
            text="This is a reply to the previous message",
            reply_context=reply_context
        )

        dest = {'keywords': []}

        # Format the message
        formatted = self.handler.format_message(msg, dest)

        # Verify reply context appears in formatted message
        self.assertIn("**  Replying to:**", formatted)
        self.assertIn("@originaluser", formatted)
        self.assertIn("2025-01-01 12:00:00 UTC", formatted)
        self.assertIn("**  Original message:**", formatted)
        self.assertIn("This is the original message being replied to", formatted)

        # Verify the actual message text is also present
        self.assertIn("This is a reply to the previous message", formatted)


if __name__ == '__main__':
    unittest.main()
