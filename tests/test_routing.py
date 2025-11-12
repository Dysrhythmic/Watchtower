"""
Refactored tests for MessageRouter and related routing logic.

This consolidates test_message_router.py (936 lines) into a cleaner structure
using pytest fixtures and parametrization (~200 lines).

Tests cover:
- Keyword matching (case-insensitive, partial matches)
- Channel ID matching and routing
- Parser functionality (trim_front_lines, trim_back_lines)
- Per-destination configuration (restricted_mode, OCR)
- RSS feed routing
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS


# ============================================================================
# KEYWORD MATCHING TESTS
# ============================================================================

class TestKeywordMatching:
    """Tests for keyword matching and routing logic."""

    def test_match_keywords_case_insensitive(self, mock_message_router, message_factory,
                                              mock_config):
        """Test keyword matching is case-insensitive."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['cve', 'ransomware'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(channel_id="@test_channel", text="New CVE discovered")
        destinations = router.get_destinations(msg)

        assert len(destinations) == 1
        assert 'cve' in destinations[0]['keywords']

    def test_empty_keywords_forwards_all(self, mock_message_router, message_factory,
                                         mock_config):
        """Test empty keywords list forwards all messages."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': [],  # Empty - forward all
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(channel_id="@test_channel", text="Any message")
        destinations = router.get_destinations(msg)

        assert len(destinations) == 1

    def test_keyword_matching_ocr_text(self, mock_message_router, message_factory,
                                       mock_config):
        """Test keyword matching includes OCR text."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['cve'],
                'restricted_mode': False,
                'parser': None,
                'ocr': True  # OCR enabled
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(
            channel_id="@test_channel",
            text="Regular text",
            ocr_raw="Contains CVE-2025-1234"
        )
        destinations = router.get_destinations(msg)

        assert len(destinations) == 1

    def test_no_match_wrong_channel(self, mock_message_router, message_factory,
                                    mock_config):
        """Test no match when channel ID doesn't match."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['cve'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(channel_id="@different_channel", text="CVE-2025-1234")
        destinations = router.get_destinations(msg)

        assert len(destinations) == 0

    def test_multiple_keyword_matches(self, mock_message_router, message_factory,
                                      mock_config):
        """Test message matching multiple keywords."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['cve', 'ransomware'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(
            channel_id="@test_channel",
            text="This message contains both CVE and ransomware"
        )
        destinations = router.get_destinations(msg)

        assert len(destinations) == 1
        assert 'cve' in destinations[0]['keywords']
        assert 'ransomware' in destinations[0]['keywords']


# ============================================================================
# PARSER TESTS
# ============================================================================

class TestParser:
    """Tests for message parsing and trimming."""

    @pytest.mark.parametrize("trim_front,trim_back,expected_content", [
        (2, 0, ["Line 3", "Line 4"]),           # Trim first 2 lines
        (0, 2, ["Line 1", "Line 2"]),           # Trim last 2 lines
        (1, 1, ["Line 2", "Line 3"]),           # Trim both ends
        (0, 0, ["Line 1", "Line 2", "Line 3", "Line 4"]),  # No trimming
    ])
    def test_parser_trimming(self, mock_message_router, message_factory,
                             trim_front, trim_back, expected_content):
        """Test parser with various trim configurations."""
        msg = message_factory(text="Line 1\nLine 2\nLine 3\nLine 4")

        parser = {'trim_front_lines': trim_front, 'trim_back_lines': trim_back}
        parsed = mock_message_router.parse_msg(msg, parser)

        for expected_line in expected_content:
            assert expected_line in parsed.text

    def test_parser_strips_all_content_shows_placeholder(self, mock_config,
                                                         message_factory):
        """
        Test that parser returns placeholder when all content is stripped.

        Tests: Bug #3 - Parser placeholder behavior
        """
        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(text="Line 1\nLine 2")

        # Parser that strips all content
        parser_config = {'trim_front_lines': 1, 'trim_back_lines': 1}
        parsed = router.parse_msg(msg, parser_config)

        # Should return placeholder message
        assert "[Message content removed by parser:" in parsed.text
        assert "first 1" in parsed.text
        assert "last 1" in parsed.text
        assert "Line 1" not in parsed.text
        assert "Line 2" not in parsed.text

    def test_parser_strips_more_lines_than_exist(self, mock_config,
                                                  message_factory):
        """Test when parser tries to remove more lines than exist."""
        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(text="Line 1\nLine 2")

        # Try to trim 5 front lines when only 2 exist
        parser_config = {'trim_front_lines': 5, 'trim_back_lines': 0}
        parsed = router.parse_msg(msg, parser_config)

        # Should return placeholder
        assert "[Message content removed by parser:" in parsed.text
        assert "Line 1" not in parsed.text
        assert "Line 2" not in parsed.text

    def test_parser_with_negative_values(self, mock_message_router, message_factory):
        """Test parser with negative values (should be treated as zero)."""
        msg = message_factory(text="Line 1\nLine 2\nLine 3")

        # Use negative values
        parser_config = {'trim_front_lines': -2, 'trim_back_lines': -1}
        parsed = mock_message_router.parse_msg(msg, parser_config)

        # Should return original text (negative treated as zero)
        assert parsed.text == msg.text

    def test_parser_does_not_affect_keyword_matching(self, message_factory, mock_config):
        """
        Test that parser has no effect on keyword matching.
        Keyword matching should happen on original message text before parsing.
        """
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@test_channel',
                'keywords': ['keyword'],
                'restricted_mode': False,
                'parser': {'trim_front_lines': 1, 'trim_back_lines': 0},
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        # Message where keyword is in line that will be trimmed
        msg = message_factory(
            channel_id="@test_channel",
            text="First line with keyword\nSecond line without it"
        )

        # Should match because keyword is in original text (before parsing)
        destinations = router.get_destinations(msg)
        assert len(destinations) == 1, "Should match keyword even though it will be trimmed"

        # Now test parsing - the keyword line should be removed
        parsed = router.parse_msg(msg, destinations[0]['parser'])
        assert "keyword" not in parsed.text, "Parser should remove the line with keyword"
        assert "Second line" in parsed.text, "Parser should preserve non-trimmed lines"


# ============================================================================
# CHANNEL CONFIGURATION TESTS
# ============================================================================

class TestChannelConfiguration:
    """Tests for per-channel and per-destination configuration."""

    def test_is_channel_restricted_true(self, mock_config):
        """Test checking if a channel has restricted mode enabled."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@restricted_channel',
                'keywords': [],
                'restricted_mode': True,  # Restricted mode enabled
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        result = router.is_channel_restricted(
            '@restricted_channel', '@restricted_channel', APP_TYPE_TELEGRAM
        )
        assert result is True

    def test_is_channel_restricted_false(self, mock_config):
        """Test checking if a channel has restricted mode disabled."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@open_channel',
                'keywords': [],
                'restricted_mode': False,  # Restricted mode disabled
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        result = router.is_channel_restricted(
            '@open_channel', '@open_channel', APP_TYPE_TELEGRAM
        )
        assert result is False

    def test_is_ocr_enabled_for_channel_true(self, mock_config):
        """Test checking if OCR is enabled for a channel."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@ocr_channel',
                'keywords': [],
                'restricted_mode': False,
                'ocr': True  # OCR enabled
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        result = router.is_ocr_enabled_for_channel(
            '@ocr_channel', '@ocr_channel', APP_TYPE_TELEGRAM
        )
        assert result is True

    def test_is_ocr_enabled_for_channel_false(self, mock_config):
        """Test checking if OCR is disabled for a channel."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': '@no_ocr_channel',
                'keywords': [],
                'restricted_mode': False,
                'ocr': False  # OCR disabled
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        result = router.is_ocr_enabled_for_channel(
            '@no_ocr_channel', '@no_ocr_channel', APP_TYPE_TELEGRAM
        )
        assert result is False


# ============================================================================
# PARSER KEEP FIRST LINES TESTS
# ============================================================================

class TestParserKeepFirstLines:
    """Tests for keep_first_lines parser option."""

    def test_parser_keeps_first_lines_and_omits_rest(self, mock_config, message_factory):
        """Test parser keeps only first N lines with omission notice."""
        from MessageRouter import MessageRouter

        router = MessageRouter(mock_config)
        msg = message_factory(text="Line 1\nLine 2\nLine 3\nLine 4\nLine 5")

        parser_config = {'keep_first_lines': 3}
        parsed = router.parse_msg(msg, parser_config)

        assert "Line 1" in parsed.text
        assert "Line 2" in parsed.text
        assert "Line 3" in parsed.text
        assert "[2 more line(s) omitted by parser]" in parsed.text
        assert "Line 4" not in parsed.text
        assert "Line 5" not in parsed.text

    def test_parser_keep_first_lines_when_fewer_lines_than_limit(self, mock_config, message_factory):
        """Test parser preserves all lines when message is shorter than limit."""
        from MessageRouter import MessageRouter

        router = MessageRouter(mock_config)
        msg = message_factory(text="Line 1\nLine 2")

        parser_config = {'keep_first_lines': 10}
        parsed = router.parse_msg(msg, parser_config)

        assert "Line 1" in parsed.text
        assert "Line 2" in parsed.text
        assert "omitted" not in parsed.text

    def test_parser_keep_first_lines_with_zero_keeps_all(self, mock_config, message_factory):
        """Test parser with zero or negative keep_first_lines preserves original message."""
        from MessageRouter import MessageRouter

        router = MessageRouter(mock_config)
        msg = message_factory(text="Line 1\nLine 2")

        parser_config = {'keep_first_lines': 0}
        parsed = router.parse_msg(msg, parser_config)

        assert parsed.text == msg.text


# ============================================================================
# ATTACHMENT KEYWORD MATCHING TESTS
# ============================================================================

class TestAttachmentKeywordMatching:
    """Tests for keyword matching with attachment content."""

    def test_keywords_match_in_attachment_when_enabled(self, mock_config, message_factory, temp_text_file):
        """Test keyword matching includes attachment text when check_attachments is True."""
        from MessageRouter import MessageRouter

        temp_path = temp_text_file(
            content="This file contains the keyword ransomware",
            suffix='.txt'
        )

        try:
            mock_config.destinations = [{
                'name': 'Test Dest',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['ransomware'],
                    'check_attachments': True,
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]

            router = MessageRouter(mock_config)
            msg = message_factory(
                channel_id="@test_channel",
                text="Regular message without keyword",
                attachment_path=temp_path
            )

            destinations = router.get_destinations(msg)

            assert len(destinations) == 1
            assert 'ransomware' in destinations[0]['keywords']
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_attachment_ignored_when_check_disabled(self, mock_config, message_factory, temp_text_file):
        """Test keyword matching skips attachment when check_attachments is False."""
        from MessageRouter import MessageRouter

        temp_path = temp_text_file(
            content="This file contains the keyword ransomware",
            suffix='.txt'
        )

        try:
            mock_config.destinations = [{
                'name': 'Test Dest',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['ransomware'],
                    'check_attachments': False,
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]

            router = MessageRouter(mock_config)
            msg = message_factory(
                channel_id="@test_channel",
                text="Regular message without keyword",
                attachment_path=temp_path
            )

            destinations = router.get_destinations(msg)

            assert len(destinations) == 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_attachment_returns_only_matched_keywords(self, mock_config, message_factory, temp_text_file):
        """Test that attachment matching returns only keywords that matched, not all configured keywords.

        This test verifies the bug fix where attachments were incorrectly reporting all configured
        keywords as matched instead of just the subset that actually matched in the file.
        """
        from MessageRouter import MessageRouter

        # Create file with lots of 'A's and only the word "test"
        content = "A" * 100 + "\n" + "A" * 100 + "\n" + "test\n" + "A" * 100
        temp_path = temp_text_file(content=content, suffix='.txt')

        try:
            # Configure many keywords, but only "test" is in the file
            mock_config.destinations = [{
                'name': 'Test Dest',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['test', 'ransomware', 'cve', 'malware', 'exploit'],
                    'check_attachments': True,
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]

            router = MessageRouter(mock_config)
            msg = message_factory(
                channel_id="@test_channel",
                text="Message without keywords in text",
                attachment_path=temp_path
            )

            destinations = router.get_destinations(msg)

            # Should match the destination
            assert len(destinations) == 1

            # But should only report "test" as matched, not all keywords
            matched_keywords = destinations[0]['keywords']
            assert len(matched_keywords) == 1, f"Expected 1 matched keyword, got {len(matched_keywords)}: {matched_keywords}"
            assert 'test' in matched_keywords, f"Expected 'test' in matched keywords, got: {matched_keywords}"
            assert 'ransomware' not in matched_keywords, "Should not match 'ransomware' - it's not in the file"
            assert 'cve' not in matched_keywords, "Should not match 'cve' - it's not in the file"
            assert 'malware' not in matched_keywords, "Should not match 'malware' - it's not in the file"
            assert 'exploit' not in matched_keywords, "Should not match 'exploit' - it's not in the file"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_keywords_match_in_both_attachment_and_text(self, mock_config, message_factory, temp_text_file):
        """Test that keywords are matched in BOTH attachment and text, and all matches are reported.

        This verifies that the system checks both sources and combines the results,
        rather than stopping after the attachment matches.
        """
        from MessageRouter import MessageRouter

        # Create attachment with "ransomware"
        temp_path = temp_text_file(content="This file contains ransomware", suffix='.txt')

        try:
            mock_config.destinations = [{
                'name': 'Test Dest',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['cve', 'ransomware', 'malware'],
                    'check_attachments': True,
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]

            router = MessageRouter(mock_config)
            msg = message_factory(
                channel_id="@test_channel",
                text="CVE-2025-1234 discovered in popular software",  # Contains "cve"
                attachment_path=temp_path  # Contains "ransomware"
            )

            destinations = router.get_destinations(msg)

            # Should match the destination
            assert len(destinations) == 1

            # Should report BOTH keywords: "cve" from text AND "ransomware" from attachment
            matched_keywords = destinations[0]['keywords']
            assert len(matched_keywords) == 2, f"Expected 2 matched keywords, got {len(matched_keywords)}: {matched_keywords}"
            assert 'ransomware' in matched_keywords, "Should match 'ransomware' from attachment"
            assert 'cve' in matched_keywords, "Should match 'cve' from message text"
            assert 'malware' not in matched_keywords, "Should not match 'malware' - not in either source"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_keywords_deduplicated_when_in_both_sources(self, mock_config, message_factory, temp_text_file):
        """Test that keywords appearing in both attachment and text are only reported once."""
        from MessageRouter import MessageRouter

        # Create attachment with "ransomware"
        temp_path = temp_text_file(content="This file contains ransomware", suffix='.txt')

        try:
            mock_config.destinations = [{
                'name': 'Test Dest',
                'type': 'Discord',
                'discord_webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['ransomware', 'malware'],
                    'check_attachments': True,
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]

            router = MessageRouter(mock_config)
            msg = message_factory(
                channel_id="@test_channel",
                text="Alert: ransomware detected in network",  # Contains "ransomware"
                attachment_path=temp_path  # Also contains "ransomware"
            )

            destinations = router.get_destinations(msg)

            # Should match the destination
            assert len(destinations) == 1

            # Should report "ransomware" only once, not twice
            matched_keywords = destinations[0]['keywords']
            assert len(matched_keywords) == 1, f"Expected 1 matched keyword (deduplicated), got {len(matched_keywords)}: {matched_keywords}"
            assert 'ransomware' in matched_keywords
            # Verify it's not duplicated by checking the list
            assert matched_keywords.count('ransomware') == 1, "Keyword should only appear once in the list"
        finally:
            Path(temp_path).unlink(missing_ok=True)


# ============================================================================
# RSS ROUTING TESTS
# ============================================================================

class TestRSSRouting:
    """Tests for RSS feed routing."""

    def test_rss_source_routing(self, message_factory, mock_config):
        """Test routing RSS source messages."""
        mock_config.destinations = [{
            'name': 'Test Dest',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook',
            'channels': [{
                'id': 'https://example.com/feed.xml',
                'keywords': ['cve'],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }]

        from MessageRouter import MessageRouter
        router = MessageRouter(mock_config)

        msg = message_factory(
            source_type="RSS",
            channel_id="https://example.com/feed.xml",
            channel_name="RSS Feed",
            text="RSS entry text with CVE"
        )

        destinations = router.get_destinations(msg)
        assert len(destinations) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
