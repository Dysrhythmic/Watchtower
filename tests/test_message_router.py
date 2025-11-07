"""
Test MessageRouter - Keyword matching and message routing logic

This module tests the MessageRouter component which determines which destinations
should receive each message based on keyword matching and channel configuration.

What This Tests:
    - Keyword matching (case-insensitive, partial matches)
    - Empty keyword lists (forward all messages)
    - Channel ID matching (with/without -100 prefix)
    - OCR text inclusion in keyword searches
    - Parser functionality (trim_front_lines, trim_back_lines)
    - Per-destination configuration (restricted_mode, parser, OCR)
    - RSS feed routing

Test Pattern - Keyword Matching:
    1. Create mock ConfigManager with destinations list
    2. Configure channel with keywords in destinations[0]['channels'][0]['keywords']
    3. Create MessageData with text that should/shouldn't match
    4. Call router.get_destinations(msg)
    5. Assert correct number of matching destinations

Test Pattern - Parser Testing:
    1. Create MessageData with multi-line text
    2. Define parser dict: {'trim_front_lines': N, 'trim_back_lines': M}
    3. Call router.parse_msg(msg, parser)
    4. Assert correct lines were removed

Mock Setup Template:
    self.mock_config = Mock()
    self.mock_config.destinations = [{
        'name': 'Destination Name',
        'type': 'discord',  # or 'telegram'
        'discord_webhook_url': 'https://discord.com/webhook',  # for Discord
        'channels': [{
            'id': '@channel_name',  # or numeric ID
            'keywords': ['keyword1', 'keyword2'],  # or [] for all messages
            'restricted_mode': False,
            'parser': None,  # or {'trim_front_lines': 0, 'trim_back_lines': 0}
            'ocr': False
        }]
    }]

How to Add New Tests:
    1. Add test method starting with test_
    2. Use descriptive docstring describing what behavior is tested""
    3. Create MessageData with relevant content
    4. Call router method being tested
    5. Use self.assertEqual/assertTrue/assertIn to verify behavior
    6. For keyword tests: check len(destinations) and matched keywords
    7. For parser tests: verify trimmed text matches expected output
"""
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
    """Test MessageRouter keyword matching and routing logic."""

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
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
        self.mock_config.destinations[0]['channels'][0]['keywords'] = []

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
        self.mock_config.destinations[0]['channels'][0]['id'] = "-1001234567890"

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
        self.mock_config.destinations[0]['channels'][0]['ocr'] = True

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
        self.mock_config.destinations[0]['channels'][0]['id'] = "https://example.com/feed.xml"

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
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
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
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
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
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
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
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
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
        mock_config.config_dir = Path("/tmp/config")
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


class TestParserKeywordIndependence(unittest.TestCase):
    """Test that parser does not affect keyword matching."""

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()
        self.mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['keyword'],
                'restricted_mode': False,
                'parser': {'trim_front_lines': 1, 'trim_back_lines': 0},
                'ocr': False
            }]
        }]
        self.router = MessageRouter(self.mock_config)

    def test_parser_does_not_affect_keyword_matching(self):
        """
        Test that parser has no effect on keyword matching for any destinations.
        Keyword matching should happen on original message text before parsing.
        """
        # Message where keyword is in line that will be trimmed
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="First line with keyword\nSecond line without it"
        )

        # Should match because keyword is in original text (before parsing)
        destinations = self.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1,
            "Should match keyword even though it will be trimmed by parser")

        # Now test parsing - the keyword line should be removed
        parsed = self.router.parse_msg(msg, destinations[0]['parser'])
        self.assertNotIn("keyword", parsed.text,
            "Parser should have removed the line with keyword from output")
        self.assertIn("Second line", parsed.text,
            "Parser should preserve non-trimmed lines")


class TestParserEdgeCases(unittest.TestCase):
    """Test parser edge cases with extreme values."""

    def setUp(self):
        """Create MessageRouter with mocked config."""
        self.mock_config = Mock()
        self.router = MessageRouter(self.mock_config)

    def test_parser_strips_more_lines_than_exist(self):
        """
        Test when parser tries to remove more lines than exist in message.
        Should return placeholder message.
        """
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2"
        )

        # Try to trim 5 front lines when only 2 exist
        parser_config = {'trim_front_lines': 5, 'trim_back_lines': 0}
        parsed = self.router.parse_msg(msg, parser_config)

        # Should return placeholder
        self.assertIn("[Message content removed by parser:", parsed.text)
        self.assertNotIn("Line 1", parsed.text)
        self.assertNotIn("Line 2", parsed.text)

    def test_parser_with_negative_values(self):
        """
        Test parser with negative values for trim_front_lines and trim_back_lines.
        Negative values should be treated as zero (no trimming).
        """
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3"
        )

        # Use negative values
        parser_config = {'trim_front_lines': -2, 'trim_back_lines': -1}
        parsed = self.router.parse_msg(msg, parser_config)

        # Should return original text (negative treated as zero)
        self.assertEqual(parsed.text, msg.text,
            "Negative trim values should not affect the message")


class TestMultipleDestinationsConfig(unittest.TestCase):
    """
    Test multiple destinations with different configurations.

    Ensures that when a single message routes to multiple destinations,
    each destination's specific config (restricted_mode, parser) is
    applied independently without affecting others.
    """

    def test_restricted_mode_for_some_destinations_not_others(self):
        """
        Test that restricted mode is applied per-destination.

        Scenario: Same channel routes to 2 destinations:
        - Destination A: restricted_mode=True (blocks certain media)
        - Destination B: restricted_mode=False (allows all media)

        Expected: Media should be blocked for Dest A but sent to Dest B.
        """
        from Watchtower import Watchtower
        from MessageData import MessageData
        from datetime import datetime, timezone
        from unittest.mock import Mock, AsyncMock
        from pathlib import Path
        import asyncio

        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        mock_config.destinations = [
            {
                'name': 'Dest A (Restricted)',
                'type': 'discord',
                'discord_webhook_url': 'https://discord.com/webhook_a',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': True,  # Restricted
                    'parser': None,
                    'ocr': False
                }]
            },
            {
                'name': 'Dest B (Open)',
                'type': 'discord',
                'discord_webhook_url': 'https://discord.com/webhook_b',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,  # Not restricted
                    'parser': None,
                    'ocr': False
                }]
            }
        ]

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)
        mock_telegram._is_media_restricted = Mock(return_value=True)  # Media IS restricted
        mock_telegram.download_media = AsyncMock(return_value="/tmp/media.jpg")

        mock_router = MessageRouter(mock_config)

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text or "")

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=False)

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
        app = Watchtower(
            sources=['telegram'],
            config=mock_config,
            telegram=mock_telegram,
            discord=mock_discord,
            router=mock_router,
            ocr=mock_ocr,
            message_queue=mock_queue,
            metrics=mock_metrics
        )

        # Create message with restricted media (photo)
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Message with photo",
            has_media=True,
            media_type="photo"
        )
        msg.original_message = Mock()

        # Process message
        asyncio.run(app._handle_message(msg, False))

        # Verify both destinations received the message
        self.assertEqual(mock_discord.send_message.call_count, 2,
            "Message should be sent to both destinations")

        # Check the send_message calls
        calls = mock_discord.send_message.call_args_list

        # First call (Dest A - restricted) should NOT include media
        self.assertIsNone(calls[0][0][2],  # media_path argument
            "Restricted destination should not receive media")

        # Second call (Dest B - not restricted) SHOULD include media
        self.assertIsNotNone(calls[1][0][2],  # media_path argument
            "Non-restricted destination should receive media")

    def test_different_parsers_per_destination(self):
        """
        Test that different parsers are applied per-destination.

        Scenario: Same channel routes to 2 destinations:
        - Destination A: Parser trims first 2 lines
        - Destination B: No parser (original text)

        Expected: Each destination gets appropriately parsed content.
        """
        from Watchtower import Watchtower
        from MessageData import MessageData
        from datetime import datetime, timezone
        from unittest.mock import Mock
        from pathlib import Path
        import asyncio

        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)

        mock_router = Mock()

        # Create two destination configs with different parsers
        dest_a_parser = {'trim_front_lines': 2, 'trim_back_lines': 0}
        dest_b_parser = None

        mock_router.get_destinations = Mock(return_value=[
            {'name': 'Dest A', 'type': 'discord', 'discord_webhook_url': 'url_a',
             'parser': dest_a_parser, 'restricted_mode': False, 'ocr': False, 'keywords': []},
            {'name': 'Dest B', 'type': 'discord', 'discord_webhook_url': 'url_b',
             'parser': dest_b_parser, 'restricted_mode': False, 'ocr': False, 'keywords': []}
        ])

        # Mock parse_msg to actually apply the parser
        def mock_parse(msg, parser):
            parsed = MessageData(
                source_type=msg.source_type,
                channel_id=msg.channel_id,
                channel_name=msg.channel_name,
                username=msg.username,
                timestamp=msg.timestamp,
                text=msg.text
            )
            if parser and parser.get('trim_front_lines', 0) > 0:
                lines = msg.text.split('\n')
                trimmed = lines[parser['trim_front_lines']:]
                parsed.text = '\n'.join(trimmed)
            return parsed

        mock_router.parse_msg = Mock(side_effect=mock_parse)
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text)

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=False)

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
        app = Watchtower(
            sources=['telegram'],
            config=mock_config,
            telegram=mock_telegram,
            discord=mock_discord,
            router=mock_router,
            ocr=mock_ocr,
            message_queue=mock_queue,
            metrics=mock_metrics
        )

        # Create message with multiple lines
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3\nLine 4"
        )

        # Process message
        asyncio.run(app._handle_message(msg, False))

        # Verify parse_msg was called twice with different parsers
        self.assertEqual(mock_router.parse_msg.call_count, 2)

        # Verify different parsers were passed
        call_1_parser = mock_router.parse_msg.call_args_list[0][0][1]
        call_2_parser = mock_router.parse_msg.call_args_list[1][0][1]

        self.assertEqual(call_1_parser, dest_a_parser,
            "First destination should use parser A")
        self.assertIsNone(call_2_parser,
            "Second destination should have no parser")


if __name__ == '__main__':
    unittest.main()
