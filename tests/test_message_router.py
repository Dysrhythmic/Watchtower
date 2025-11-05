import unittest
import sys
import os
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageRouter import MessageRouter
from MessageData import MessageData
from TelegramHandler import TelegramHandler
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument


class TestMessageRouter(unittest.TestCase):
    """Test MessageRouter."""

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()
        self.mock_config.webhooks = [{
            'name': 'Test Dest',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['cve', 'ransomware'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]
        self.router = MessageRouter(self.mock_config)

    def test_match_keywords_case_insensitive(self):
        """Test keyword matching is case-insensitive."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="New CVE discovered"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)
        self.assertIn('cve', destinations[0]['keywords'])

    def test_empty_keywords_forwards_all(self):
        """Test empty keywords list forwards all messages."""
        self.mock_config.webhooks[0]['channels'][0]['keywords'] = []

        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Any message"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)

    def test_parser_trim_front_lines(self):
        """Test parser removes first N lines."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3\nLine 4"
        )

        parser = {'trim_front_lines': 2, 'trim_back_lines': 0}
        parsed = self.router.parse_msg(msg, parser)

        self.assertNotIn("Line 1", parsed.text)
        self.assertNotIn("Line 2", parsed.text)
        self.assertIn("Line 3", parsed.text)
        self.assertIn("Line 4", parsed.text)

    def test_parser_trim_back_lines(self):
        """Test parser removes last N lines."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3\nLine 4"
        )

        parser = {'trim_front_lines': 0, 'trim_back_lines': 2}
        parsed = self.router.parse_msg(msg, parser)

        self.assertIn("Line 1", parsed.text)
        self.assertIn("Line 2", parsed.text)
        self.assertNotIn("Line 3", parsed.text)
        self.assertNotIn("Line 4", parsed.text)

    def test_channel_match_numeric_id(self):
        """Test channel matching with numeric ID."""
        self.mock_config.webhooks[0]['channels'][0]['id'] = "-1001234567890"

        msg = MessageData(
            source_type="telegram",
            channel_id="-1001234567890",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="ransomware alert"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)

    def test_keyword_matching_ocr_text(self):
        """Test keyword matching includes OCR text."""
        self.mock_config.webhooks[0]['channels'][0]['ocr'] = True

        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Regular text",
            ocr_raw="Contains CVE-2025-1234"
        )

        destinations = self.router.get_destinations(msg)
        # Should match because OCR text contains keyword
        self.assertEqual(len(destinations), 1)

    def test_no_match_wrong_channel(self):
        """Test no match when channel ID doesn't match."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@different_channel",
            channel_name="Different",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="CVE-2025-1234"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 0)

    def test_parser_both_trim_directions(self):
        """Test parser trims both front and back lines."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Front\nMiddle1\nMiddle2\nBack"
        )

        parser_config = {
            'trim_front_lines': 1,
            'trim_back_lines': 1
        }

        parsed = self.router.parse_msg(msg, parser_config)
        self.assertNotIn("Front", parsed.text)
        self.assertNotIn("Back", parsed.text)
        self.assertIn("Middle1", parsed.text)
        self.assertIn("Middle2", parsed.text)

    def test_parser_no_trimming(self):
        """Test parser with no trimming configured."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3"
        )

        parsed = self.router.parse_msg(msg, None)
        self.assertEqual(parsed.text, msg.text)

    def test_multiple_keyword_matches(self):
        """Test message matching multiple keywords."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="This message contains both CVE and ransomware"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)
        # Should include both matched keywords
        self.assertIn('cve', destinations[0]['keywords'])
        self.assertIn('ransomware', destinations[0]['keywords'])

    def test_rss_source_routing(self):
        """Test routing RSS source messages."""
        self.mock_config.webhooks[0]['channels'][0]['id'] = "https://example.com/feed.xml"

        msg = MessageData(
            source_type="rss",
            channel_id="https://example.com/feed.xml",
            channel_name="RSS Feed",
            username="RSS",
            timestamp=datetime.now(timezone.utc),
            text="RSS entry text with CVE"
        )

        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)


class TestMessageRouterBranchCoverage(unittest.TestCase):
    """
    Tests for MessageRouter branch coverage.

    These tests cover previously untested branches:
    - is_channel_restricted() branches (lines 24-26)
    - is_ocr_enabled_for_channel() branches (lines 33-35)
    """

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()

    def test_is_channel_restricted_true(self):
        """
        Given: Channel with restricted_mode=True in config
        When: is_channel_restricted() called
        Then: Returns True

        Tests: src/MessageRouter.py:24-25 (restricted mode True branch)
        """
        # Configure webhook with restricted channel
        self.mock_config.webhooks = [{
            'name': 'Test Dest',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@restricted_channel',
                'keywords': [],
                'restricted_mode': True,  # Restricted mode enabled
                'ocr': False
            }]
        }]

        router = MessageRouter(self.mock_config)

        # Test with matching channel
        result = router.is_channel_restricted('@restricted_channel', '@restricted_channel')

        # Should return True
        self.assertTrue(result)

    def test_is_channel_restricted_false(self):
        """
        Given: Channel with restricted_mode=False (or not set) in config
        When: is_channel_restricted() called
        Then: Returns False

        Tests: src/MessageRouter.py:26 (restricted mode False branch)
        """
        # Configure webhook with non-restricted channel
        self.mock_config.webhooks = [{
            'name': 'Test Dest',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@open_channel',
                'keywords': [],
                'restricted_mode': False,  # Restricted mode disabled
                'ocr': False
            }]
        }]

        router = MessageRouter(self.mock_config)

        # Test with matching channel
        result = router.is_channel_restricted('@open_channel', '@open_channel')

        # Should return False
        self.assertFalse(result)

    def test_is_ocr_enabled_for_channel_true(self):
        """
        Given: Channel with ocr=True in config
        When: is_ocr_enabled_for_channel() called
        Then: Returns True

        Tests: src/MessageRouter.py:33-34 (OCR enabled True branch)
        """
        # Configure webhook with OCR enabled
        self.mock_config.webhooks = [{
            'name': 'Test Dest',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@ocr_channel',
                'keywords': [],
                'restricted_mode': False,
                'ocr': True  # OCR enabled
            }]
        }]

        router = MessageRouter(self.mock_config)

        # Test with matching channel
        result = router.is_ocr_enabled_for_channel('@ocr_channel', '@ocr_channel')

        # Should return True
        self.assertTrue(result)

    def test_is_ocr_enabled_for_channel_false(self):
        """
        Given: Channel with ocr=False (or not set) in config
        When: is_ocr_enabled_for_channel() called
        Then: Returns False

        Tests: src/MessageRouter.py:35 (OCR enabled False branch)
        """
        # Configure webhook with OCR disabled
        self.mock_config.webhooks = [{
            'name': 'Test Dest',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@no_ocr_channel',
                'keywords': [],
                'restricted_mode': False,
                'ocr': False  # OCR disabled
            }]
        }]

        router = MessageRouter(self.mock_config)

        # Test with matching channel
        result = router.is_ocr_enabled_for_channel('@no_ocr_channel', '@no_ocr_channel')

        # Should return False
        self.assertFalse(result)


class TestParserPlaceholder(unittest.TestCase):
    """
    Tests for parser placeholder behavior.

    These tests cover Bug #3: RSS parser posting original + stripped message.
    """

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()
        self.router = MessageRouter(self.mock_config)

    def test_parser_strips_all_content_shows_placeholder(self):
        """
        Given: Message with 2 lines and parser that strips both lines
        When: parse_msg() called
        Then: Returns placeholder message (not original content)

        Tests: Bug #3 - Parser placeholder behavior
        Reproduces: Both original and stripped message posted separately

        This test verifies only the placeholder is returned when all content is stripped.
        """
        msg = MessageData(
            source_type="rss",
            channel_id="https://example.com/feed",
            channel_name="RSS Feed",
            username="RSS",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2"
        )

        # Parser that strips all content (both lines)
        parser_config = {
            'trim_front_lines': 1,
            'trim_back_lines': 1
        }

        parsed = self.router.parse_msg(msg, parser_config)

        # Should return placeholder message
        self.assertIn("[Message content removed by parser:", parsed.text)
        self.assertIn("first 1", parsed.text)
        self.assertIn("last 1", parsed.text)

        # Should NOT contain original content
        self.assertNotIn("Line 1", parsed.text)
        self.assertNotIn("Line 2", parsed.text)

    def test_parser_strips_single_line_shows_placeholder(self):
        """
        Given: Message with single line and parser that strips it
        When: parse_msg() called
        Then: Returns placeholder message

        Tests: Bug #3 - Parser placeholder for single-line messages
        """
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Only line"
        )

        # Parser that strips the only line
        parser_config = {'trim_front_lines': 1, 'trim_back_lines': 0}

        parsed = self.router.parse_msg(msg, parser_config)

        # Should show placeholder
        self.assertIn("[Message content removed by parser:", parsed.text)
        self.assertIn("first 1", parsed.text)

        # Should NOT contain original
        self.assertNotIn("Only line", parsed.text)

class TestIsMediaRestrictedBugFix(unittest.TestCase):
    """Test that _is_media_restricted() returns True when media IS restricted."""

    def setUp(self):
        """Set up test handler."""
        mock_config = Mock()
        mock_config.project_root = Path("/tmp")
        mock_config.api_id = "123"
        mock_config.api_hash = "abc"

        with patch('TelegramHandler.TelegramClient'):
            self.handler = TelegramHandler(mock_config)

    def test_photo_should_be_restricted(self):
        """
        Test that _is_media_restricted() returns TRUE when a photo is restricted.

        Expected behavior:
        - Photo media is NOT allowed in restricted mode
        - Therefore, _is_media_restricted() should return True (media IS restricted)

        This test will FAIL with current implementation (currently returns False).
        """
        mock_msg = Mock()
        mock_msg.media = MessageMediaPhoto()

        is_restricted = self.handler._is_media_restricted(mock_msg)

        # Photo should be restricted, so function should return True
        self.assertTrue(
            is_restricted,
            "Photo media should be restricted - function should return True"
        )

    def test_no_media_should_not_be_restricted(self):
        """
        Test that _is_media_restricted() returns FALSE when no media (not restricted).

        Expected behavior:
        - Messages without media are allowed
        - Therefore, _is_media_restricted() should return False (media is NOT restricted)

        This test will FAIL with current implementation (currently returns True).
        """
        mock_msg = Mock()
        mock_msg.media = None

        is_restricted = self.handler._is_media_restricted(mock_msg)

        # No media should NOT be restricted, so function should return False
        self.assertFalse(
            is_restricted,
            "No media should NOT be restricted - function should return False"
        )

    def test_allowed_document_should_not_be_restricted(self):
        """
        Test that _is_media_restricted() returns FALSE for allowed documents.

        Expected behavior:
        - CSV document with correct MIME is allowed
        - Therefore, _is_media_restricted() should return False (media is NOT restricted)

        This test will FAIL with current implementation (currently returns True).
        """
        # Create mock message with allowed CSV document
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.mime_type = "text/csv"

        mock_attr = Mock()
        mock_attr.file_name = "data.csv"
        message.media.document.attributes = [mock_attr]

        is_restricted = self.handler._is_media_restricted(message)

        # Allowed CSV should NOT be restricted, so function should return False
        self.assertFalse(
            is_restricted,
            "Allowed CSV document should NOT be restricted - function should return False"
        )

    def test_malware_document_should_be_restricted(self):
        """
        Test that _is_media_restricted() returns TRUE for malware documents.

        Expected behavior:
        - Document with .csv extension but executable MIME is blocked
        - Therefore, _is_media_restricted() should return True (media IS restricted)

        This test will FAIL with current implementation (currently returns False).
        """
        # Create mock message with malware (safe extension, malicious MIME)
        message = Mock()
        message.media = Mock(spec=MessageMediaDocument)
        message.media.document = Mock()
        message.media.document.mime_type = "application/x-msdownload"  # Executable!

        mock_attr = Mock()
        mock_attr.file_name = "malware.csv"  # Looks safe but isn't
        message.media.document.attributes = [mock_attr]

        is_restricted = self.handler._is_media_restricted(message)

        # Malware should be restricted, so function should return True
        self.assertTrue(
            is_restricted,
            "Malware document should be restricted - function should return True"
        )


if __name__ == '__main__':
    unittest.main()
