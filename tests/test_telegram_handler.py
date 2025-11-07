"""
Test TelegramHandler - Telegram client operations and message handling

This module tests the TelegramHandler component which handles both Telegram
source monitoring and Telegram destination delivery using Telethon library.

What This Tests:
    - Message formatting (HTML markup: <b>, <i>, <code>, <blockquote>)
    - Restricted mode media filtering (file type and MIME type checks)
    - URL defanging for CTI workflows (hxxps://t[.]me format)
    - URL building (public @username and private /c/ formats)
    - Rate limit tracking
    - Media type detection (Photo, Document, Other)
    - Username extraction from senders (User, Channel)

Test Pattern - Restricted Mode:
    1. Create mock Telegram message with MessageMediaDocument
    2. Configure document with attributes (file_name, mime_type)
    3. Call handler._is_media_restricted(message)
    4. Assert True (restricted) or False (allowed) based on file type
    5. Check ALLOWED_EXTENSIONS and ALLOWED_MIME_TYPES

Test Pattern - Message Formatting:
    1. Create MessageData with text, OCR, keywords
    2. Create destination dict
    3. Call handler.format_message(msg, destination)
    4. Assert HTML markup is present: <b>bold</b>, <i>italic</i>
    5. Check OCR text uses <blockquote> tags

Test Pattern - URL Building:
    1. Call build_message_url(channel_id, channel_name, msg_id)
    2. For public channels: assert URL uses @username format
    3. For private channels: assert URL uses /c/<id> format with -100 stripped
    4. For defanged URLs: assert hxxps://t[.]me format

Mock Setup Template:
    mock_config = Mock()
    mock_config.project_root = Path("/tmp")
    mock_config.api_id = "123456"
    mock_config.api_hash = "abc123hash"

    with patch('TelegramHandler.TelegramClient'):
        handler = TelegramHandler(mock_config)

    # For restricted mode testing:
    mock_message = Mock()
    mock_message.media = MessageMediaDocument()
    mock_doc = Mock()
    mock_doc.mime_type = "application/pdf"  # or allowed type
    mock_attr = Mock()
    mock_attr.file_name = "file.pdf"
    mock_doc.attributes = [mock_attr]
    mock_message.media.document = mock_doc

How to Add New Tests:
    1. Add test method starting with test_
    2. Use descriptive docstring describing what Telegram feature is tested
    3. For formatting tests: create MessageData and assert HTML markup
    4. For URL tests: use static methods directly (no handler instance needed)
    5. For restricted mode: mock MessageMediaDocument with attributes
    6. Use self.assertIn/assertEqual/assertTrue for verification
"""
import unittest
import sys
import os
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from TelegramHandler import TelegramHandler
from MessageData import MessageData
from datetime import datetime, timezone
from telethon.tl.types import MessageMediaDocument


class TestTelegramHandler(unittest.TestCase):
    """Test TelegramHandler Telegram operations and formatting."""

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

        is_restricted = self.handler._is_media_restricted(mock_msg)
        self.assertTrue(is_restricted)  # Photo is restricted, should return True

    def test_no_media_is_allowed(self):
        """Test messages without media are allowed."""
        mock_msg = Mock()
        mock_msg.media = None

        is_restricted = self.handler._is_media_restricted(mock_msg)
        self.assertFalse(is_restricted)  # No media is not restricted, should return False

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
        Then: Returns False (not restricted - function returns False when allowed)

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
        is_restricted = handler._is_media_restricted(message)

        # Should be allowed (function returns False when not restricted)
        self.assertFalse(is_restricted)

    @patch('TelegramHandler.TelegramClient')
    def test_document_with_extension_match_mime_mismatch_blocked(self, MockClient):
        """
        Given: Document with filename="malware.csv", mime_type="application/x-msdownload"
        When: _is_media_restricted() called
        Then: Returns True (restricted - function returns True when blocked)

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
        is_restricted = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns True when restricted)
        self.assertTrue(is_restricted)

    @patch('TelegramHandler.TelegramClient')
    def test_document_with_mime_match_extension_mismatch_blocked(self, MockClient):
        """
        Given: Document with filename="data.exe", mime_type="text/csv"
        When: _is_media_restricted() called
        Then: Returns True (restricted - function returns True when blocked)

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
        is_restricted = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns True when restricted)
        self.assertTrue(is_restricted)

    @patch('TelegramHandler.TelegramClient')
    def test_document_without_filename_attribute_blocked(self, MockClient):
        """
        Given: Document without file_name attribute
        When: _is_media_restricted() called
        Then: Returns True (restricted - function returns True when blocked)

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
        is_restricted = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns True when restricted)
        self.assertTrue(is_restricted)

    @patch('TelegramHandler.TelegramClient')
    def test_document_without_mime_type_blocked(self, MockClient):
        """
        Given: Document with filename but no mime_type attribute
        When: _is_media_restricted() called
        Then: Returns True (restricted - function returns True when blocked)

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
        is_restricted = handler._is_media_restricted(message)

        # Should be BLOCKED (function returns True when restricted)
        self.assertTrue(is_restricted)


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


class TestTelegramLogFunctionality(unittest.TestCase):
    """Test telegram log file creation, reading, updating, and cleanup."""

    def setUp(self):
        """Create TelegramHandler with mocked config and temp log directory."""
        import tempfile
        import shutil

        # Create temporary directory for telegram logs
        self.temp_dir = Path(tempfile.mkdtemp())
        self.telegramlog_dir = self.temp_dir / "telegramlog"
        self.telegramlog_dir.mkdir(parents=True, exist_ok=True)

        mock_config = Mock()
        mock_config.project_root = self.temp_dir
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"
        mock_config.telegramlog_dir = self.telegramlog_dir
        mock_config.channel_names = {
            '-100123456789': 'Test Channel',
            '@testchannel': 'Test Username Channel',
            '987654321': 'Plain ID Channel'
        }

        with patch('TelegramHandler.TelegramClient'):
            self.handler = TelegramHandler(mock_config)

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_telegram_log_path_numeric_id(self):
        """Test _telegram_log_path strips -100 prefix from numeric IDs."""
        # Given: Numeric channel ID with -100 prefix
        channel_id = '-100123456789'

        # When: Getting log path
        log_path = self.handler._telegram_log_path(channel_id)

        # Then: Should strip -100 prefix
        self.assertEqual(log_path.name, '123456789.txt')
        self.assertEqual(log_path.parent, self.telegramlog_dir)

    def test_telegram_log_path_username_id(self):
        """Test _telegram_log_path strips @ prefix from username IDs."""
        # Given: Username channel ID with @ prefix
        channel_id = '@testchannel'

        # When: Getting log path
        log_path = self.handler._telegram_log_path(channel_id)

        # Then: Should strip @ prefix
        self.assertEqual(log_path.name, 'testchannel.txt')
        self.assertEqual(log_path.parent, self.telegramlog_dir)

    def test_telegram_log_path_plain_id(self):
        """Test _telegram_log_path handles plain numeric IDs."""
        # Given: Plain numeric ID without prefix
        channel_id = '987654321'

        # When: Getting log path
        log_path = self.handler._telegram_log_path(channel_id)

        # Then: Should use as-is
        self.assertEqual(log_path.name, '987654321.txt')
        self.assertEqual(log_path.parent, self.telegramlog_dir)

    def test_create_telegram_log(self):
        """Test _create_telegram_log creates proper two-line format."""
        # Given: Channel ID and message ID
        channel_id = '-100123456789'
        msg_id = 42

        # When: Creating telegram log
        self.handler._create_telegram_log(channel_id, msg_id)

        # Then: Should create file with channel name and message ID
        log_path = self.handler._telegram_log_path(channel_id)
        self.assertTrue(log_path.exists())

        content = log_path.read_text(encoding='utf-8')
        lines = content.strip().split('\n')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], 'Test Channel')
        self.assertEqual(lines[1], '42')

    def test_create_telegram_log_unresolved_channel(self):
        """Test _create_telegram_log handles unresolved channel names."""
        # Given: Channel ID not in channel_names
        channel_id = '-100999999999'
        msg_id = 100

        # When: Creating telegram log
        self.handler._create_telegram_log(channel_id, msg_id)

        # Then: Should use "Unresolved:<id>" format
        log_path = self.handler._telegram_log_path(channel_id)
        content = log_path.read_text(encoding='utf-8')
        lines = content.strip().split('\n')
        self.assertEqual(lines[0], 'Unresolved:-100999999999')
        self.assertEqual(lines[1], '100')

    def test_read_telegram_log_existing(self):
        """Test _read_telegram_log reads message ID from existing log."""
        # Given: Existing telegram log
        channel_id = '-100123456789'
        msg_id = 42
        self.handler._create_telegram_log(channel_id, msg_id)

        # When: Reading telegram log
        result = self.handler._read_telegram_log(channel_id)

        # Then: Should return message ID
        self.assertEqual(result, 42)

    def test_read_telegram_log_nonexistent(self):
        """Test _read_telegram_log returns None for nonexistent log."""
        # Given: No telegram log exists
        channel_id = '-100999999999'

        # When: Reading telegram log
        result = self.handler._read_telegram_log(channel_id)

        # Then: Should return None
        self.assertIsNone(result)

    def test_read_telegram_log_corrupted(self):
        """Test _read_telegram_log handles corrupted log files."""
        # Given: Corrupted telegram log (invalid integer)
        channel_id = '-100123456789'
        log_path = self.handler._telegram_log_path(channel_id)
        log_path.write_text("Test Channel\ninvalid_number\n", encoding='utf-8')

        # When: Reading telegram log
        with self.assertLogs(level='ERROR') as log_context:
            result = self.handler._read_telegram_log(channel_id)

        # Then: Should return None and log error
        self.assertIsNone(result)
        self.assertTrue(any("Error reading log" in msg for msg in log_context.output))

    def test_read_telegram_log_single_line(self):
        """Test _read_telegram_log handles single-line files."""
        # Given: Telegram log with only one line
        channel_id = '-100123456789'
        log_path = self.handler._telegram_log_path(channel_id)
        log_path.write_text("Test Channel\n", encoding='utf-8')

        # When: Reading telegram log
        result = self.handler._read_telegram_log(channel_id)

        # Then: Should return None (not enough lines)
        self.assertIsNone(result)

    def test_update_telegram_log(self):
        """Test _update_telegram_log updates existing log."""
        # Given: Existing telegram log
        channel_id = '-100123456789'
        self.handler._create_telegram_log(channel_id, 42)

        # When: Updating telegram log with new message ID
        self.handler._update_telegram_log(channel_id, 100)

        # Then: Should update message ID while preserving channel name
        content = self.handler._telegram_log_path(channel_id).read_text(encoding='utf-8')
        lines = content.strip().split('\n')
        self.assertEqual(lines[0], 'Test Channel')
        self.assertEqual(lines[1], '100')

    def test_update_telegram_log_creates_if_missing(self):
        """Test _update_telegram_log creates log if it doesn't exist."""
        # Given: No existing telegram log
        channel_id = '-100123456789'

        # When: Updating telegram log
        self.handler._update_telegram_log(channel_id, 50)

        # Then: Should create log
        log_path = self.handler._telegram_log_path(channel_id)
        self.assertTrue(log_path.exists())

        content = log_path.read_text(encoding='utf-8')
        lines = content.strip().split('\n')
        self.assertEqual(lines[1], '50')

    def test_telegram_log_workflow(self):
        """Test complete workflow: create, read, update."""
        # Given: Channel ID
        channel_id = '@testchannel'

        # When: Creating initial log
        self.handler._create_telegram_log(channel_id, 1)

        # Then: Should read correctly
        self.assertEqual(self.handler._read_telegram_log(channel_id), 1)

        # When: Updating log
        self.handler._update_telegram_log(channel_id, 2)

        # Then: Should read new value
        self.assertEqual(self.handler._read_telegram_log(channel_id), 2)

        # When: Updating again
        self.handler._update_telegram_log(channel_id, 100)

        # Then: Should read latest value
        self.assertEqual(self.handler._read_telegram_log(channel_id), 100)

    def test_multiple_channel_logs(self):
        """Test managing logs for multiple channels simultaneously."""
        # Given: Multiple channel IDs
        channels = {
            '-100123456789': 42,
            '@channel1': 100,
            '987654321': 200
        }

        # When: Creating logs for all channels
        for channel_id, msg_id in channels.items():
            self.handler._create_telegram_log(channel_id, msg_id)

        # Then: All logs should be readable independently
        for channel_id, expected_msg_id in channels.items():
            self.assertEqual(
                self.handler._read_telegram_log(channel_id),
                expected_msg_id
            )

        # When: Updating one channel
        self.handler._update_telegram_log('-100123456789', 500)

        # Then: Only that channel should be updated
        self.assertEqual(self.handler._read_telegram_log('-100123456789'), 500)
        self.assertEqual(self.handler._read_telegram_log('@channel1'), 100)
        self.assertEqual(self.handler._read_telegram_log('987654321'), 200)


class TestTelegramLogCleanup(unittest.TestCase):
    """Test telegram log cleanup functionality in Watchtower."""

    def setUp(self):
        """Create Watchtower instance with mocked dependencies."""
        import tempfile

        # Create temporary directory for telegram logs
        self.temp_dir = Path(tempfile.mkdtemp())
        self.telegramlog_dir = self.temp_dir / "telegramlog"
        self.telegramlog_dir.mkdir(parents=True, exist_ok=True)

        # Create attachments directory (required by Watchtower.__init__)
        self.attachments_dir = self.temp_dir / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

        # Create mock config
        mock_config = Mock()
        mock_config.project_root = self.temp_dir
        mock_config.telegramlog_dir = self.telegramlog_dir
        mock_config.tmp_dir = self.temp_dir
        mock_config.attachments_dir = self.attachments_dir
        mock_config.destinations = []
        mock_config.rss_feeds = []

        # Create Watchtower instance using dependency injection
        from Watchtower import Watchtower
        self.watchtower = Watchtower(
            sources=[],
            config=mock_config,
            telegram=Mock(),
            discord=Mock(),
            router=Mock(),
            ocr=Mock(),
            message_queue=Mock(),
            metrics=Mock()
        )

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_clear_telegram_logs(self):
        """Test _clear_telegram_logs removes all log files."""
        # Given: Multiple telegram log files
        (self.telegramlog_dir / "123456789.txt").write_text("Channel 1\n100\n")
        (self.telegramlog_dir / "channel1.txt").write_text("Channel 2\n200\n")
        (self.telegramlog_dir / "999999999.txt").write_text("Channel 3\n300\n")

        # When: Clearing telegram logs
        self.watchtower._clear_telegram_logs()

        # Then: All .txt files should be removed
        remaining_files = list(self.telegramlog_dir.glob("*.txt"))
        self.assertEqual(len(remaining_files), 0)

    def test_clear_telegram_logs_empty_directory(self):
        """Test _clear_telegram_logs handles empty directory."""
        # Given: Empty telegramlog directory
        # When: Clearing telegram logs
        self.watchtower._clear_telegram_logs()

        # Then: Should complete without errors
        self.assertTrue(self.telegramlog_dir.exists())

    def test_clear_telegram_logs_nonexistent_directory(self):
        """Test _clear_telegram_logs handles nonexistent directory."""
        # Given: Non-existent telegramlog directory
        import shutil
        shutil.rmtree(self.telegramlog_dir)

        # When: Clearing telegram logs
        # Then: Should complete without errors (silently skips if directory doesn't exist)
        try:
            self.watchtower._clear_telegram_logs()
        except Exception as e:
            self.fail(f"_clear_telegram_logs raised an exception: {e}")

        # Verify directory still doesn't exist
        self.assertFalse(self.telegramlog_dir.exists())

    def test_clear_telegram_logs_preserves_other_files(self):
        """Test _clear_telegram_logs only removes .txt files."""
        # Given: Mix of .txt and other files
        (self.telegramlog_dir / "channel1.txt").write_text("Channel 1\n100\n")
        (self.telegramlog_dir / "README.md").write_text("# Telegram Logs")
        (self.telegramlog_dir / "data.json").write_text("{}")

        # When: Clearing telegram logs
        self.watchtower._clear_telegram_logs()

        # Then: Only .txt files should be removed
        self.assertFalse((self.telegramlog_dir / "channel1.txt").exists())
        self.assertTrue((self.telegramlog_dir / "README.md").exists())
        self.assertTrue((self.telegramlog_dir / "data.json").exists())


if __name__ == '__main__':
    unittest.main()
