"""
Tests for RSSHandler functionality.

This file merges:
- TestRSSHandler class from test_handlers.py (basic formatting tests)
- All content from test_rss_integration.py (integration tests)

These tests cover critical RSS polling logic that ensures:
- First run initialization doesn't emit old messages
- Deduplication prevents message floods
- Timestamp tracking works correctly
- Entry filtering by age works
- HTML stripping works correctly
"""

import unittest
import sys
import os
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from RSSHandler import RSSHandler
from MessageData import MessageData


class TestRSSHandler(unittest.TestCase):
    """Test RSSHandler basic functionality."""

    def setUp(self):
        """Create RSSHandler with mocked config."""
        import tempfile
        import shutil
        self.temp_dir = Path(tempfile.mkdtemp())

        mock_config = Mock()
        mock_config.rsslog_dir = self.temp_dir / "rsslog"
        mock_config.rsslog_dir.mkdir(parents=True, exist_ok=True)
        self.handler = RSSHandler(mock_config, lambda msg, is_latest: True)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_strip_html_tags(self):
        """Test HTML tag stripping."""
        html = "<p>Test <a href='url'>link</a> text</p>"
        clean = self.handler._strip_html_tags(html)
        self.assertEqual(clean, "Test link text")

    def test_strip_html_entities(self):
        """Test HTML entity decoding."""
        html = "&lt;test&gt; &amp; &quot;quotes&quot;"
        clean = self.handler._strip_html_tags(html)
        self.assertEqual(clean, '<test> & "quotes"')

    def test_format_entry_truncate_summary(self):
        """Test summary truncation at 1000 chars."""
        entry = Mock()
        entry.title = "Title"
        entry.link = "https://example.com"
        entry.summary = "x" * 1500

        formatted = self.handler._format_entry_text(entry)
        self.assertIn("Title", formatted)
        self.assertIn("https://example.com", formatted)
        self.assertIn("...", formatted)
        # Summary should be truncated
        summary_line = [line for line in formatted.split('\n') if 'x' in line][0]
        self.assertLess(len(summary_line), 1100)

    def test_strip_html_nested_tags(self):
        """Test stripping nested HTML tags."""
        html = "<div><p>Paragraph <strong>bold <em>italic</em></strong></p></div>"
        clean = self.handler._strip_html_tags(html)
        self.assertEqual(clean, "Paragraph bold italic")

    def test_strip_html_preserves_newlines(self):
        """Test HTML stripping preserves spacing."""
        html = "<p>Line 1</p>\n<p>Line 2</p>"
        clean = self.handler._strip_html_tags(html)
        self.assertIn("Line 1", clean)
        self.assertIn("Line 2", clean)

    def test_format_entry_no_summary(self):
        """Test formatting entry without summary."""
        entry = Mock()
        entry.title = "Just a title"
        entry.link = "https://example.com"
        entry.summary = ""

        formatted = self.handler._format_entry_text(entry)
        self.assertIn("Just a title", formatted)
        self.assertIn("https://example.com", formatted)

    def test_format_entry_with_html_in_title(self):
        """Test HTML entities in title are decoded."""
        entry = Mock()
        entry.title = "Test &amp; Example"
        entry.link = "https://example.com"
        entry.summary = "Summary"

        formatted = self.handler._format_entry_text(entry)
        self.assertIn("Test & Example", formatted)

    def test_format_entry_special_characters(self):
        """Test formatting handles special characters."""
        entry = Mock()
        entry.title = "Title with émojis 🎉 and spëcial chars"
        entry.link = "https://example.com"
        entry.summary = "Summary with 中文 characters"

        formatted = self.handler._format_entry_text(entry)
        self.assertIn("émojis", formatted)
        self.assertIn("🎉", formatted)
        self.assertIn("中文", formatted)


class TestRSSHandlerTimestampTracking(unittest.TestCase):
    """Tests for timestamp reading/writing functionality."""

    def setUp(self):
        """Create temp directory for RSS logs."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_config = Mock()
        self.mock_config.rsslog_dir = Path(self.temp_dir.name)
        self.mock_on_message = AsyncMock(return_value=True)

    def tearDown(self):
        """Cleanup temp directory."""
        self.temp_dir.cleanup()

    def test_first_run_initializes_timestamp_emits_nothing(self):
        """
        Given: No timestamp file exists for feed
        When: _read_last_ts() called
        Then: File created with current time, returns None

        Tests: src/RSSHandler.py:40-45 (first run initialization)

        This is CRITICAL - prevents message flood on first run.
        """
        handler = RSSHandler(self.mock_config, self.mock_on_message)
        rss_name = "test_feed"

        # Verify file doesn't exist
        log_path = self.mock_config.rsslog_dir / f"{rss_name}.txt"
        self.assertFalse(log_path.exists())

        # When: Read timestamp (first run)
        result = handler._read_last_ts(rss_name)

        # Then: Returns None (no messages emitted)
        self.assertIsNone(result)

        # And: File created with current timestamp
        self.assertTrue(log_path.exists())
        content = log_path.read_text().strip()
        # Should be ISO format timestamp
        self.assertIn('T', content)  # ISO format has T separator

    def test_subsequent_run_reads_existing_timestamp(self):
        """
        Given: Timestamp file exists with timestamp
        When: _read_last_ts() called
        Then: Returns timestamp as float

        Tests: src/RSSHandler.py:46-53 (subsequent run)
        """
        handler = RSSHandler(self.mock_config, self.mock_on_message)
        rss_name = "test_feed"

        # Create existing timestamp file
        log_path = self.mock_config.rsslog_dir / f"{rss_name}.txt"
        test_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        log_path.write_text(test_dt.isoformat(), encoding='utf-8')

        # When: Read timestamp
        result = handler._read_last_ts(rss_name)

        # Then: Returns timestamp
        self.assertIsNotNone(result)
        self.assertEqual(result, test_dt.timestamp())

    def test_write_last_ts_updates_file(self):
        """
        Given: Timestamp to write
        When: _write_last_ts() called
        Then: File updated with new timestamp

        Tests: src/RSSHandler.py:55-58 (timestamp writing)
        """
        handler = RSSHandler(self.mock_config, self.mock_on_message)
        rss_name = "test_feed"

        test_timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        # When: Write timestamp
        handler._write_last_ts(rss_name, test_timestamp)

        # Then: File contains timestamp
        log_path = self.mock_config.rsslog_dir / f"{rss_name}.txt"
        self.assertTrue(log_path.exists())

        # Read it back
        result = handler._read_last_ts(rss_name)
        self.assertEqual(result, test_timestamp)


class TestRSSHandlerEntryProcessing(unittest.TestCase):
    """Tests for RSS entry parsing and filtering."""

    def setUp(self):
        """Create handler with temp directory."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_config = Mock()
        self.mock_config.rsslog_dir = Path(self.temp_dir.name)
        self.mock_on_message = AsyncMock(return_value=True)
        self.handler = RSSHandler(self.mock_config, self.mock_on_message)

    def tearDown(self):
        """Cleanup temp directory."""
        self.temp_dir.cleanup()

    def test_entry_already_seen_skipped(self):
        """
        Given: Entry with timestamp <= last_timestamp
        When: _process_entry() called
        Then: Returns (None, None) - entry skipped

        Tests: src/RSSHandler.py:115-116 (deduplication)

        This is CRITICAL - prevents duplicate message floods.
        """
        # Create entry with old timestamp
        entry = Mock()
        entry.updated_parsed = time.gmtime(1000000)  # Old timestamp
        entry.title = "Test Entry"
        entry.link = "http://test.com"
        entry.summary = "Test summary"

        last_timestamp = 2000000  # Newer than entry
        cutoff_timestamp = 0  # Allow old entries for this test

        # When: Process entry
        message_data, timestamp = asyncio.run(
            self.handler._process_entry(entry, "http://feed.com", "test_feed", last_timestamp, cutoff_timestamp)
        )

        # Then: Entry skipped (deduplication)
        self.assertIsNone(message_data)

    def test_entry_too_old_skipped(self):
        """
        Given: Entry older than MAX_ENTRY_AGE_DAYS
        When: _process_entry() called
        Then: Returns (None, None) - entry skipped

        Tests: src/RSSHandler.py:112-113 (age filtering)

        This prevents message floods after extended downtime.
        """
        # Create entry 3 days old (older than MAX_ENTRY_AGE_DAYS = 2)
        three_days_ago = time.time() - (3 * 86400)
        entry = Mock()
        entry.updated_parsed = time.gmtime(three_days_ago)
        entry.title = "Old Entry"
        entry.link = "http://test.com"
        entry.summary = "Old summary"

        cutoff_timestamp = time.time() - (self.handler.MAX_ENTRY_AGE_DAYS * 86400)

        # When: Process entry
        message_data, timestamp = asyncio.run(
            self.handler._process_entry(entry, "http://feed.com", "test_feed", None, cutoff_timestamp)
        )

        # Then: Entry skipped (too old)
        self.assertIsNone(message_data)

    def test_entry_new_and_recent_processed(self):
        """
        Given: Entry that is new and recent
        When: _process_entry() called
        Then: Returns MessageData with correct fields

        Tests: src/RSSHandler.py:118-130 (entry processing)
        """
        # Create recent entry
        recent_time = time.time() - 3600  # 1 hour ago
        entry = Mock()
        entry.updated_parsed = time.gmtime(recent_time)
        entry.title = "New Entry"
        entry.link = "http://test.com/new"
        entry.summary = "New content"

        cutoff_timestamp = time.time() - (self.handler.MAX_ENTRY_AGE_DAYS * 86400)

        # When: Process entry
        message_data, timestamp = asyncio.run(
            self.handler._process_entry(entry, "http://feed.com", "test_feed", None, cutoff_timestamp)
        )

        # Then: MessageData created
        self.assertIsNotNone(message_data)
        self.assertEqual(message_data.source_type, "rss")
        self.assertEqual(message_data.channel_id, "http://feed.com")
        self.assertEqual(message_data.channel_name, "test_feed")
        self.assertEqual(message_data.username, "RSS")
        self.assertIn("New Entry", message_data.text)
        self.assertIn("http://test.com/new", message_data.text)
        self.assertFalse(message_data.has_media)

    def test_extract_entry_timestamp_prefers_updated(self):
        """
        Given: Entry with both updated_parsed and published_parsed
        When: _extract_entry_timestamp() called
        Then: Returns updated_parsed (preferred)

        Tests: src/RSSHandler.py:60-66 (timestamp extraction)
        """
        entry = Mock()
        entry.updated_parsed = time.gmtime(2000000)
        entry.published_parsed = time.gmtime(1000000)

        result = self.handler._extract_entry_timestamp(entry)

        # Should prefer updated_parsed
        self.assertEqual(result, time.mktime(time.gmtime(2000000)))

    def test_extract_entry_timestamp_falls_back_to_published(self):
        """
        Given: Entry with only published_parsed
        When: _extract_entry_timestamp() called
        Then: Returns published_parsed

        Tests: src/RSSHandler.py:62-65 (fallback logic)
        """
        entry = Mock()
        # No updated_parsed
        entry.updated_parsed = None
        entry.published_parsed = time.gmtime(1000000)

        result = self.handler._extract_entry_timestamp(entry)

        self.assertEqual(result, time.mktime(time.gmtime(1000000)))

    def test_extract_entry_timestamp_no_timestamp_returns_none(self):
        """
        Given: Entry without timestamp fields
        When: _extract_entry_timestamp() called
        Then: Returns None

        Tests: src/RSSHandler.py:60-66 (missing timestamp)
        """
        entry = Mock()
        entry.updated_parsed = None
        entry.published_parsed = None

        result = self.handler._extract_entry_timestamp(entry)

        self.assertIsNone(result)


class TestRSSHandlerHTMLStripping(unittest.TestCase):
    """Tests for HTML tag removal functionality."""

    def setUp(self):
        """Create handler."""
        self.mock_config = Mock()
        self.mock_on_message = AsyncMock(return_value=True)
        self.handler = RSSHandler(self.mock_config, self.mock_on_message)

    def test_strip_html_tags_removes_all_tags(self):
        """
        Given: Text with HTML tags
        When: _strip_html_tags() called
        Then: All tags removed, entities decoded

        Tests: src/RSSHandler.py:69-81 (HTML stripping)
        """
        html_text = "<p>Hello <b>world</b>! Visit <a href='url'>link</a>.</p>"

        result = self.handler._strip_html_tags(html_text)

        self.assertEqual(result, "Hello world! Visit link.")
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)

    def test_strip_html_tags_decodes_entities(self):
        """
        Given: Text with HTML entities
        When: _strip_html_tags() called
        Then: Entities decoded to characters

        Tests: src/RSSHandler.py:79-80 (entity decoding)
        """
        html_text = "Test &lt;tag&gt; &amp; &quot;quotes&quot; &nbsp;"

        result = self.handler._strip_html_tags(html_text)

        # &nbsp; decodes to \xa0 (non-breaking space Unicode character)
        self.assertEqual(result, "Test <tag> & \"quotes\" \xa0")

    def test_strip_html_numeric_entities(self):
        """
        Given: Text with numeric HTML entities from RSS feeds
        When: _strip_html_tags() called
        Then: All numeric entities decoded to Unicode characters

        Tests: Bug #1 - Numeric entity decoding
        Reproduces: [&#8230;] &#8211; &#8217; &#8220; &#8221;

        This test should FAIL before fix and PASS after fix.
        """
        html_text = "Test [&#8230;] and &#8211; also &#8217;quote&#8217; &#8220;double&#8221;"

        result = self.handler._strip_html_tags(html_text)

        # Should decode all numeric entities
        # Note: &#8217; decodes to RIGHT SINGLE QUOTATION MARK (U+2019)
        # &#8220; and &#8221; decode to LEFT/RIGHT DOUBLE QUOTATION MARKS (U+201C, U+201D)
        expected = "Test […] and – also \u2019quote\u2019 \u201cdouble\u201d"
        self.assertEqual(result, expected)
        # Should NOT contain raw entity codes
        self.assertNotIn('&#8230;', result)
        self.assertNotIn('&#8211;', result)
        self.assertNotIn('&#8217;', result)
        self.assertNotIn('&#8220;', result)
        self.assertNotIn('&#8221;', result)

    def test_format_entry_text_truncates_long_summary(self):
        """
        Given: Entry with summary > 1000 chars
        When: _format_entry_text() called
        Then: Summary truncated to 1000 chars + " ..."

        Tests: src/RSSHandler.py:97-98 (summary truncation)
        """
        entry = Mock()
        entry.title = "Test Title"
        entry.link = "http://test.com"
        entry.summary = "A" * 1500  # 1500 chars

        result = self.handler._format_entry_text(entry)

        # Should have truncated summary
        self.assertIn("A" * 1000, result)
        self.assertIn(" ...", result)
        self.assertLess(len(result), 1500)


class TestRSSHandlerFeedPolling(unittest.TestCase):
    """Tests for feed polling and error handling."""

    def setUp(self):
        """Create handler with temp directory."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mock_config = Mock()
        self.mock_config.rsslog_dir = Path(self.temp_dir.name)
        self.mock_on_message = AsyncMock(return_value=True)
        self.handler = RSSHandler(self.mock_config, self.mock_on_message)

    def tearDown(self):
        """Cleanup temp directory."""
        self.temp_dir.cleanup()

    @patch('feedparser.parse')
    def test_feed_parse_error_logged_not_raised(self, mock_feedparser):
        """
        Given: feedparser.parse() returns feed with bozo=True
        When: run_feed() processes feed
        Then: Error logged but not raised, polling continues

        Tests: src/RSSHandler.py:147-148 (parse error handling)
        """
        # Create feed with parse error
        mock_feed = Mock()
        mock_feed.bozo = True
        mock_feed.bozo_exception = Exception("Parse error")
        mock_feed.entries = []
        mock_feedparser.return_value = mock_feed

        feed_config = {
            'rss_url': 'http://test.com/feed',
            'rss_name': 'test_feed'
        }

        # Run one iteration
        async def run_one_iteration():
            # Initialize timestamp
            self.handler._read_last_ts('test_feed')

            # Mock sleep to exit after one iteration
            original_sleep = self.handler._sleep
            call_count = 0

            async def mock_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count >= 1:
                    raise asyncio.CancelledError()
                await original_sleep(0.01)

            self.handler._sleep = mock_sleep

            try:
                await self.handler.run_feed(feed_config)
            except asyncio.CancelledError:
                pass

        with self.assertLogs(level='ERROR') as log_context:
            asyncio.run(run_one_iteration())

        # Error should be logged
        self.assertTrue(any("Parse error" in msg for msg in log_context.output))

    @patch('feedparser.parse')
    def test_poll_interval_respected(self, mock_feedparser):
        """
        Given: Feed configured
        When: run_feed() runs
        Then: Sleeps for DEFAULT_POLL_INTERVAL between polls

        Tests: src/RSSHandler.py:184 (poll interval)
        """
        mock_feed = Mock()
        mock_feed.bozo = False
        mock_feed.entries = []
        mock_feedparser.return_value = mock_feed

        feed_config = {
            'rss_url': 'http://test.com/feed',
            'rss_name': 'test_feed'
        }

        sleep_durations = []

        # Mock _sleep to capture sleep duration
        async def mock_sleep(seconds):
            sleep_durations.append(seconds)
            raise asyncio.CancelledError()  # Exit after first iteration

        self.handler._sleep = mock_sleep

        # Run one iteration
        async def run_one_iteration():
            try:
                await self.handler.run_feed(feed_config)
            except asyncio.CancelledError:
                pass

        asyncio.run(run_one_iteration())

        # Should have called sleep with DEFAULT_POLL_INTERVAL
        self.assertEqual(len(sleep_durations), 1)
        self.assertEqual(sleep_durations[0], self.handler.DEFAULT_POLL_INTERVAL)


if __name__ == '__main__':
    unittest.main()
