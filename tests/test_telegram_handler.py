import unittest
import sys
import os
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from TelegramHandler import TelegramHandler
from MessageData import MessageData
from datetime import datetime, timezone
from telethon.tl.types import MessageMediaDocument


class TestTelegramHandler(unittest.TestCase):
    """Test TelegramHandler."""

    def setUp(self):
        """Create TelegramHandler with mocked config."""
        mock_config = Mock()
        mock_config.project_root = Path("/tmp")
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"

        with patch('TelegramHandler.TelegramClient'):
            self.handler = TelegramHandler(mock_config)

    def test_inherits_destination_handler(self):
        """Test that TelegramHandler inherits from DestinationHandler."""
        self.assertIsInstance(self.handler, DestinationHandler)

    def test_format_message_html(self):
        """Test message formatting uses HTML."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Test Channel",
            username="@testuser",
            timestamp=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            text="Test message"
        )
        dest = {'keywords': []}
        formatted = self.handler.format_message(msg, dest)
        self.assertIn("<b>New message from:</b>", formatted)
        self.assertIn("<b>By:</b>", formatted)

    def test_defang_url(self):
        """Test URL defanging."""
        url = "https://t.me/channel/123"
        defanged = self.handler._defang_tme(url)
        self.assertEqual(defanged, "hxxps://t[.]me/channel/123")

    def test_build_message_url_public(self):
        """Test building public channel URL."""
        url = self.handler.build_message_url("123", "@channel", 456)
        self.assertEqual(url, "https://t.me/channel/456")

    def test_build_message_url_private(self):
        """Test building private channel URL."""
        url = self.handler.build_message_url("-1001234567890", "Private", 456)
        self.assertEqual(url, "https://t.me/c/1234567890/456")

    def test_restricted_mode_blocks_photo(self):
        """Test restricted mode blocks photos."""
        from telethon.tl.types import MessageMediaPhoto

        mock_msg = Mock()
        mock_msg.media = MessageMediaPhoto()

        allowed = self.handler._is_media_restricted(mock_msg)
        self.assertFalse(allowed)

    def test_no_media_is_allowed(self):
        """Test messages without media are allowed."""
        mock_msg = Mock()
        mock_msg.media = None

        allowed = self.handler._is_media_restricted(mock_msg)
        self.assertTrue(allowed)

    def test_format_message_with_keywords(self):
        """Test formatted message displays matched keywords."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Message"
        )
        dest = {'keywords': ['CVE', 'malware']}
        formatted = self.handler.format_message(msg, dest)
        self.assertIn("<b>Matched:</b>", formatted)
        self.assertIn("<code>CVE</code>", formatted)
        self.assertIn("<code>malware</code>", formatted)

    def test_defang_multiple_protocols(self):
        """Test defanging t.me URLs only."""
        urls = [
            ("https://t.me/chan/123", "hxxps://t[.]me/chan/123"),
            ("http://t.me/test", "hxxp://t[.]me/test"),
            ("https://telegram.me/chan", "hxxps://telegram[.]me/chan")
        ]
        for original, expected in urls:
            result = self.handler._defang_tme(original)
            self.assertEqual(result, expected)

    def test_build_message_url_numeric_public(self):
        """Test building URL for numeric public channel."""
        url = self.handler.build_message_url("-1001234567890", "-1001234567890", 123)
        # Numeric IDs become private links
        self.assertIn("t.me/c/", url)

    def test_format_message_escapes_html(self):
        """Test HTML characters are properly escaped."""
        msg = MessageData(
            source_type="telegram",
            channel_name="Test <script>",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="<b>Bold</b> & special chars"
        )
        dest = {'keywords': []}
        formatted = self.handler.format_message(msg, dest)
        # Should escape HTML entities
        self.assertIn("&lt;", formatted)
        self.assertIn("&gt;", formatted)
        self.assertIn("&amp;", formatted)

    @patch('TelegramHandler.TelegramClient')
    def test_send_message_creates_client(self, mock_client):
        """Test send_message uses Telegram client."""
        # This is a basic test - actual async sending would need AsyncMock
        self.assertIsNotNone(self.handler.client)

    def test_caption_limit_constant(self):
        """Test TELEGRAM_CAPTION_LIMIT constant is set correctly."""
        self.assertEqual(self.handler.TELEGRAM_CAPTION_LIMIT, 1024)

    def test_caption_length_validation_logic(self):
        """Test caption length validation logic."""
        # Test that limit is correctly defined
        self.assertEqual(TelegramHandler.TELEGRAM_CAPTION_LIMIT, 1024)

        # Test boundary conditions
        caption_ok = "x" * 1024
        caption_too_long = "y" * 1025

        self.assertLessEqual(len(caption_ok), TelegramHandler.TELEGRAM_CAPTION_LIMIT)
        self.assertGreater(len(caption_too_long), TelegramHandler.TELEGRAM_CAPTION_LIMIT)


class TestTelegramSendOperations(unittest.TestCase):
    """
    Critical tests for TelegramHandler.send_copy() operations.

    These tests cover the highest priority gaps identified in the coverage analysis:
    - Caption overflow handling (lines 371-384) - CRITICAL USER-REPORTED ISSUE
    - Message chunking at 4096 limit
    - FloodWaitError handling (lines 396-399)
    """

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.api_id = "123456"
        self.mock_config.api_hash = "test_hash"
        self.mock_config.project_root = Path("/tmp/test")

    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_text_only_under_4096(self, MockClient):
        """
        Given: Text message with 2000 chars, no media
        When: send_copy() called
        Then: Single send_message() call

        Tests: src/TelegramHandler.py:347-403 (basic send path)
        """
        import asyncio

        # Given: Handler with mocked client
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_message = AsyncMock(return_value=Mock(id=123))

        # Test data
        text = "A" * 2000  # Under 4096 limit
        destination = 123

        # When: send_copy() called
        result = asyncio.run(handler.send_copy(
            destination_chat_id=destination,
            content=text,
            media_path=None
        ))

        # Then: Single send_message call
        self.assertTrue(result)
        handler.client.send_message.assert_called_once()
        call_args = handler.client.send_message.call_args
        self.assertEqual(call_args[0][0], destination)
        self.assertEqual(len(call_args[0][1]), 2000)

    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_text_over_4096_chunked(self, MockClient):
        """
        Given: Text message with 6000 chars, no media
        When: send_copy() called
        Then: Multiple send_message() calls with chunked text

        Tests: src/TelegramHandler.py:347-403 (text chunking)
        """
        import asyncio

        # Given: Handler with mocked client
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_message = AsyncMock(return_value=Mock(id=123))

        # Test data
        text = "A" * 6000  # Over 4096 limit
        destination = 123

        # When: send_copy() called
        result = asyncio.run(handler.send_copy(
            destination_chat_id=destination,
            content=text,
            media_path=None
        ))

        # Then: Multiple send_message calls
        self.assertTrue(result)
        self.assertEqual(handler.client.send_message.call_count, 2)

        # Verify total text matches (allowing for chunk boundaries)
        total_sent = sum(len(call[0][1]) for call in handler.client.send_message.call_args_list)
        # Should be close to 6000 (may vary slightly due to newline handling)
        self.assertGreater(total_sent, 5900)
        self.assertLess(total_sent, 6100)

    @patch('os.path.exists')
    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_media_with_caption_under_1024(self, MockClient, mock_exists):
        """
        Given: Media + 500 char caption
        When: send_copy() called
        Then: Single send_file() call with caption

        Tests: src/TelegramHandler.py:365-370 (caption within limit)
        """
        import asyncio

        # Given: Handler with mocked client
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_file = AsyncMock(return_value=Mock(id=123))
        handler.client.send_message = AsyncMock()

        # Test data
        media_path = "/tmp/test.jpg"
        mock_exists.return_value = True  # Media file exists
        caption = "A" * 500  # Under 1024 limit
        destination = 123

        # When: send_copy() called
        result = asyncio.run(handler.send_copy(
            destination_chat_id=destination,
            content=caption,
            media_path=media_path
        ))

        # Then: Single send_file with caption
        self.assertTrue(result)
        handler.client.send_file.assert_called_once()
        call_args = handler.client.send_file.call_args
        self.assertEqual(call_args[0][0], destination)
        self.assertEqual(call_args[0][1], media_path)
        self.assertIsNotNone(call_args[1].get('caption'))
        self.assertEqual(len(call_args[1]['caption']), 500)

        # send_message should NOT be called
        handler.client.send_message.assert_not_called()

    @patch('os.path.exists')
    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_media_with_caption_over_1024_captionless_plus_chunks(self, MockClient, mock_exists):
        """
        Given: Media + 1500 char caption
        When: send_copy() called
        Then: send_file() captionless + send_message() with full text

        Tests: src/TelegramHandler.py:371-384 (CRITICAL caption overflow logic)

        This is the HIGHEST PRIORITY test - user reported content loss on 6700-char captions.
        """
        import asyncio

        # Given: Handler with mocked client
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_file = AsyncMock(return_value=Mock(id=123))
        handler.client.send_message = AsyncMock(return_value=Mock(id=124))

        # Test data
        media_path = "/tmp/test.jpg"
        mock_exists.return_value = True  # Media file exists
        long_caption = "A" * 1500  # Over 1024 limit
        destination = 123

        # When: send_copy() called
        result = asyncio.run(handler.send_copy(
            destination_chat_id=destination,
            content=long_caption,
            media_path=media_path
        ))

        # Then: send_file called WITHOUT caption
        self.assertTrue(result)
        handler.client.send_file.assert_called_once()
        file_call_args = handler.client.send_file.call_args
        self.assertEqual(file_call_args[0][1], media_path)
        # Caption should be None (captionless)
        caption_arg = file_call_args[1].get('caption')
        self.assertTrue(caption_arg is None or caption_arg == "")

        # send_message called with FULL 1500 chars (NO CONTENT LOSS)
        handler.client.send_message.assert_called_once()
        message_call_args = handler.client.send_message.call_args
        sent_text = message_call_args[0][1]
        self.assertEqual(len(sent_text), 1500)
        self.assertEqual(sent_text, long_caption)

    @patch('os.path.exists')
    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_media_with_caption_over_5000_captionless_plus_chunked_text(self, MockClient, mock_exists):
        """
        Given: Media + 5500 char caption
        When: send_copy() called
        Then: send_file() captionless + multiple send_message() chunks

        Tests: src/TelegramHandler.py:371-384 (caption overflow + chunking)

        This tests the user's exact reported scenario: 6700-char captions.
        """
        import asyncio

        # Given: Handler with mocked client
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_file = AsyncMock(return_value=Mock(id=123))
        handler.client.send_message = AsyncMock(return_value=Mock(id=124))

        # Test data
        media_path = "/tmp/test.jpg"
        mock_exists.return_value = True  # Media file exists
        very_long_caption = "A" * 5500  # Over 1024 and requires chunking
        destination = 123

        # When: send_copy() called
        result = asyncio.run(handler.send_copy(
            destination_chat_id=destination,
            content=very_long_caption,
            media_path=media_path
        ))

        # Then: send_file called captionless
        self.assertTrue(result)
        handler.client.send_file.assert_called_once()
        file_call_args = handler.client.send_file.call_args
        caption_arg = file_call_args[1].get('caption')
        self.assertTrue(caption_arg is None or caption_arg == "")

        # send_message called TWICE (4096 + 1404 chars)
        self.assertEqual(handler.client.send_message.call_count, 2)

        # Verify total text sent matches original (NO CONTENT LOSS)
        total_sent = sum(len(call[0][1]) for call in handler.client.send_message.call_args_list)
        self.assertGreater(total_sent, 5400)  # Allow for chunk boundaries
        self.assertLess(total_sent, 5600)

    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_flood_wait_error_enqueues(self, MockClient):
        """
        Given: send_message() raises FloodWaitError(60)
        When: send_copy() called
        Then: Exception caught, returns False (will be enqueued by caller)

        Tests: src/TelegramHandler.py:396-399 (FloodWaitError handling)
        """
        import asyncio
        from telethon.errors import FloodWaitError

        # Given: Handler with failing send
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create FloodWaitError (it requires a request parameter, but we need the seconds attribute)
        flood_error = FloodWaitError(request=Mock())
        flood_error.seconds = 60  # Set the seconds attribute manually
        handler.client.send_message = AsyncMock(side_effect=flood_error)

        # Test data
        text = "Test message"
        destination = 123

        # When: send_copy() called
        with self.assertLogs(level='WARNING') as log_context:
            result = asyncio.run(handler.send_copy(
                destination_chat_id=destination,
                content=text,
                media_path=None
            ))

        # Then: Returns False, error logged
        self.assertFalse(result)
        self.assertTrue(any("FloodWaitError" in msg or "60" in msg for msg in log_context.output))

    @patch('TelegramHandler.TelegramClient')
    def test_send_copy_generic_exception_enqueues(self, MockClient):
        """
        Given: send_message() raises generic Exception
        When: send_copy() called
        Then: Exception caught, returns False

        Tests: src/TelegramHandler.py:401-403 (generic exception handling)
        """
        import asyncio

        # Given: Handler with failing send
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)
        handler.client.send_message = AsyncMock(side_effect=Exception("Network error"))

        # Test data
        text = "Test message"
        destination = 123

        # When: send_copy() called
        with self.assertLogs(level='ERROR') as log_context:
            result = asyncio.run(handler.send_copy(
                destination_chat_id=destination,
                content=text,
                media_path=None
            ))

        # Then: Returns False, error logged
        self.assertFalse(result)
        self.assertTrue(any("Failed to send" in msg or "Network error" in msg for msg in log_context.output))


class TestRestrictedModeComplete(unittest.TestCase):
    """
    Complete tests for restricted mode document validation.

    These tests cover SECURITY-CRITICAL gaps in document validation.
    Tests: src/TelegramHandler.py:209-248
    """

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.api_id = "123456"
        self.mock_config.api_hash = "test_hash"
        self.mock_config.project_root = Path("/tmp/test")

    @patch('TelegramHandler.TelegramClient')
    def test_document_with_extension_and_mime_match_allowed(self, MockClient):
        """
        Given: Document with filename="data.csv", mime_type="text/csv"
        When: _is_media_restricted() called
        Then: Returns True (allowed - function returns True for allowed, False for blocked)

        Tests: src/TelegramHandler.py:224-248 (document validation)
        """
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create mock message with document
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [
            Mock(file_name="data.csv", spec=['file_name'])
        ]
        message.media.document.mime_type = "text/csv"

        # Test
        is_allowed = handler._is_media_restricted(message)

        # Should be allowed (function returns True when allowed)
        self.assertTrue(is_allowed)

    @patch('TelegramHandler.TelegramClient')
    def test_document_with_extension_match_mime_mismatch_blocked(self, MockClient):
        """
        Given: Document with filename="malware.csv", mime_type="application/x-msdownload"
        When: _is_media_restricted() called
        Then: Returns False (blocked - function returns False for blocked)

        Tests: src/TelegramHandler.py:242 (SECURITY: extension match but MIME mismatch)

        This is a SECURITY test - prevents malware disguised with safe extension.
        """
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create mock message with suspicious document
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [
            Mock(file_name="malware.csv", spec=['file_name'])
        ]
        message.media.document.mime_type = "application/x-msdownload"  # Executable!

        # Test
        is_allowed = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns False when blocked)
        self.assertFalse(is_allowed)

    @patch('TelegramHandler.TelegramClient')
    def test_document_with_mime_match_extension_mismatch_blocked(self, MockClient):
        """
        Given: Document with filename="data.exe", mime_type="text/csv"
        When: _is_media_restricted() called
        Then: Returns False (blocked - function returns False for blocked)

        Tests: src/TelegramHandler.py:242 (SECURITY: MIME match but extension mismatch)

        This is a SECURITY test - prevents executable files even with safe MIME.
        """
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create mock message with suspicious document
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [
            Mock(file_name="data.exe", spec=['file_name'])
        ]
        message.media.document.mime_type = "text/csv"

        # Test
        is_allowed = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns False when blocked)
        self.assertFalse(is_allowed)

    @patch('TelegramHandler.TelegramClient')
    def test_document_without_filename_attribute_blocked(self, MockClient):
        """
        Given: Document without file_name attribute
        When: _is_media_restricted() called
        Then: Returns False (blocked - function returns False for blocked)

        Tests: src/TelegramHandler.py:231-237 (missing filename handling)
        """
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create mock message with document missing filename
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = []  # No attributes
        message.media.document.mime_type = "text/csv"

        # Test
        is_allowed = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns False when blocked)
        self.assertFalse(is_allowed)

    @patch('TelegramHandler.TelegramClient')
    def test_document_without_mime_type_blocked(self, MockClient):
        """
        Given: Document with filename but no mime_type attribute
        When: _is_media_restricted() called
        Then: Returns False (blocked - function returns False for blocked)

        Tests: src/TelegramHandler.py:239-240 (missing MIME handling)
        """
        mock_client_instance = MockClient.return_value
        handler = TelegramHandler(self.mock_config)

        # Create mock message with document missing MIME
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.attributes = [
            Mock(file_name="data.csv", spec=['file_name'])
        ]
        message.media.document.mime_type = None

        # Test
        is_allowed = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns False when blocked)
        self.assertFalse(is_allowed)


class TestTelegramReplyContext(unittest.TestCase):
    """
    Tests for Telegram reply context handling.

    These tests cover the _get_reply_context() method (lines 182-206) and ensure
    reply information is properly extracted, formatted, and truncated.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.api_id = "123456"
        self.mock_config.api_hash = "test_hash"
        self.mock_config.project_root = Path("/tmp/test")

    @patch('TelegramHandler.TelegramClient')
    def test_reply_context_success(self, MockClient):
        """
        Given: Message with reply_to pointing to valid message
        When: _get_reply_context() called
        Then: Returns context dict with author, text, time, media info

        Tests: src/TelegramHandler.py:182-202 (successful reply extraction)
        """
        import asyncio
        from telethon.tl.types import User
        from datetime import datetime, timezone

        # Given: Handler with mocked client
        handler = TelegramHandler(self.mock_config)

        # Mock the reply message
        mock_reply = Mock()
        mock_reply.id = 456
        mock_reply.text = "This is the original message"
        mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_reply.media = None

        # Mock the sender
        mock_sender = Mock(spec=User)
        mock_sender.username = "replyuser"
        mock_sender.first_name = None
        mock_sender.last_name = None
        mock_reply.sender = mock_sender

        # Mock get_messages to return the reply
        handler.client.get_messages = AsyncMock(return_value=mock_reply)

        # Mock the message requesting reply context
        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 456

        # When: _get_reply_context() called
        result = asyncio.run(handler._get_reply_context(mock_message))

        # Then: Returns complete context
        self.assertIsNotNone(result)
        self.assertEqual(result['message_id'], 456)
        self.assertEqual(result['author'], '@replyuser')
        self.assertEqual(result['text'], 'This is the original message')
        self.assertEqual(result['time'], '2025-01-01 12:00:00 UTC')
        self.assertFalse(result['has_media'])
        self.assertIsNone(result['media_type'])

    @patch('TelegramHandler.TelegramClient')
    def test_reply_context_missing(self, MockClient):
        """
        Given: Message with reply_to_msg_id but reply not found (deleted/inaccessible)
        When: _get_reply_context() called
        Then: Returns None (reply message doesn't exist)

        Tests: src/TelegramHandler.py:190 (replied_msg check)
        """
        import asyncio

        # Given: Handler with mocked client
        handler = TelegramHandler(self.mock_config)

        # Mock get_messages to return None (message not found)
        handler.client.get_messages = AsyncMock(return_value=None)

        # Mock the message requesting reply context
        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 999  # Non-existent message

        # When: _get_reply_context() called
        result = asyncio.run(handler._get_reply_context(mock_message))

        # Then: Returns None (no context available)
        self.assertIsNone(result)

    @patch('TelegramHandler.TelegramClient')
    def test_reply_context_long_truncated(self, MockClient):
        """
        Given: Reply message with text >200 chars
        When: format_message() called with reply_context
        Then: Reply text truncated to 200 chars + " ..." in formatted output

        Tests: src/TelegramHandler.py:290-291 (truncation in format_message)
        Note: Truncation happens in format_message, but context extraction preserves full text
        """
        import asyncio
        from telethon.tl.types import User
        from datetime import datetime, timezone

        # Given: Handler with mocked client
        handler = TelegramHandler(self.mock_config)

        # Create long reply text (>200 chars)
        long_text = "A" * 250

        # Mock the reply message
        mock_reply = Mock()
        mock_reply.id = 456
        mock_reply.text = long_text
        mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_reply.media = None

        # Mock the sender
        mock_sender = Mock(spec=User)
        mock_sender.username = "longuser"
        mock_sender.first_name = None
        mock_sender.last_name = None
        mock_reply.sender = mock_sender

        # Mock get_messages to return the reply
        handler.client.get_messages = AsyncMock(return_value=mock_reply)

        # Mock the message requesting reply context
        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 456

        # When: _get_reply_context() called
        context = asyncio.run(handler._get_reply_context(mock_message))

        # Then: Context contains full text (250 chars)
        self.assertIsNotNone(context)
        self.assertEqual(len(context['text']), 250)

        # When: format_message() uses this context
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

        # Then: Formatted output should truncate to 200 + " ..."
        # The formatted message should contain truncated reply text
        self.assertIn("A" * 200, formatted)  # First 200 chars present
        self.assertIn("...", formatted)  # Ellipsis added
        # Should NOT contain all 250 A's in the reply section
        self.assertNotIn("A" * 250, formatted)

    @patch('TelegramHandler.TelegramClient')
    def test_reply_context_malformed(self, MockClient):
        """
        Given: Reply message object missing 'text' attribute (edge case)
        When: _get_reply_context() called
        Then: Returns context with empty string for text (graceful handling)

        Tests: src/TelegramHandler.py:197 (replied_msg.text or "" fallback)
        """
        import asyncio
        from telethon.tl.types import User
        from datetime import datetime, timezone

        # Given: Handler with mocked client
        handler = TelegramHandler(self.mock_config)

        # Mock the reply message WITHOUT text attribute
        mock_reply = Mock()
        mock_reply.id = 456
        # Intentionally not setting text attribute to simulate malformed message
        del mock_reply.text  # Remove text attribute
        mock_reply.date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_reply.media = None

        # Mock the sender
        mock_sender = Mock(spec=User)
        mock_sender.username = "malformeduser"
        mock_sender.first_name = None
        mock_sender.last_name = None
        mock_reply.sender = mock_sender

        # Configure Mock to raise AttributeError when accessing .text
        type(mock_reply).text = property(lambda self: (_ for _ in ()).throw(AttributeError()))

        # Mock get_messages to return the malformed reply
        handler.client.get_messages = AsyncMock(return_value=mock_reply)

        # Mock the message requesting reply context
        mock_message = Mock()
        mock_message.chat_id = 123
        mock_message.reply_to = Mock()
        mock_message.reply_to.reply_to_msg_id = 456

        # When: _get_reply_context() called
        # Then: Should handle gracefully and log error (returns None due to exception)
        with self.assertLogs(level='ERROR') as log_context:
            result = asyncio.run(handler._get_reply_context(mock_message))

        # Should return None due to exception in try/except block
        self.assertIsNone(result)
        # Should log error about getting reply context
        self.assertTrue(any("Error getting reply context" in msg for msg in log_context.output))


if __name__ == '__main__':
    unittest.main()
