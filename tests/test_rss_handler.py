"""Tests for RSSHandler functionality."""
import sys
import os
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from RSSHandler import RSSHandler
from MessageData import MessageData


@pytest.fixture
def temp_dir():
    """Create temp directory for tests."""
    temp = Path(tempfile.mkdtemp())
    yield temp
    if temp.exists():
        shutil.rmtree(temp)


@pytest.fixture
def handler(temp_dir):
    """Create RSSHandler with mocked config."""
    mock_config = Mock()
    mock_config.rsslog_dir = temp_dir / "rsslog"
    mock_config.rsslog_dir.mkdir(parents=True, exist_ok=True)
    return RSSHandler(mock_config, lambda msg, is_latest: True)


@pytest.fixture
def handler_with_async_callback():
    """Create RSSHandler with async callback."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = Mock()
    mock_config.rsslog_dir = Path(temp_dir.name)
    mock_on_message = AsyncMock(return_value=True)
    handler = RSSHandler(mock_config, mock_on_message)
    yield handler
    temp_dir.cleanup()


def test_strip_html_tags(handler):
    """Test HTML tag stripping."""
    html = "<p>Test <a href='url'>link</a> text</p>"
    clean = handler._strip_html_tags(html)
    assert clean == "Test link text"


def test_strip_html_entities(handler):
    """Test HTML entity decoding."""
    html = "&lt;test&gt; &amp; &quot;quotes&quot;"
    clean = handler._strip_html_tags(html)
    assert clean == '<test> & "quotes"'


def test_format_entry_truncate_summary(handler):
    """Test summary truncation at 1000 chars."""
    entry = Mock()
    entry.title = "Title"
    entry.link = "https://example.com"
    entry.summary = "x" * 1500

    formatted = handler._format_entry_text(entry)
    assert "Title" in formatted
    assert "https://example.com" in formatted
    assert "..." in formatted
    summary_line = [line for line in formatted.split('\n') if 'x' in line][0]
    assert len(summary_line) < 1100


def test_strip_html_nested_tags(handler):
    """Test stripping nested HTML tags."""
    html = "<div><p>Paragraph <strong>bold <em>italic</em></strong></p></div>"
    clean = handler._strip_html_tags(html)
    assert clean == "Paragraph bold italic"


def test_strip_html_preserves_newlines(handler):
    """Test HTML stripping preserves spacing."""
    html = "<p>Line 1</p>\n<p>Line 2</p>"
    clean = handler._strip_html_tags(html)
    assert "Line 1" in clean
    assert "Line 2" in clean


def test_format_entry_no_summary(handler):
    """Test formatting entry without summary."""
    entry = Mock()
    entry.title = "Just a title"
    entry.link = "https://example.com"
    entry.summary = ""

    formatted = handler._format_entry_text(entry)
    assert "Just a title" in formatted
    assert "https://example.com" in formatted


def test_format_entry_with_html_in_title(handler):
    """Test HTML entities in title are decoded."""
    entry = Mock()
    entry.title = "Test &amp; Example"
    entry.link = "https://example.com"
    entry.summary = "Summary"

    formatted = handler._format_entry_text(entry)
    assert "Test & Example" in formatted


def test_format_entry_special_characters(handler):
    """Test formatting handles special characters."""
    entry = Mock()
    entry.title = "Title with émojis 🎉 and spëcial chars"
    entry.link = "https://example.com"
    entry.summary = "Summary with 中文 characters"

    formatted = handler._format_entry_text(entry)
    assert "émojis" in formatted
    assert "🎉" in formatted
    assert "中文" in formatted


def test_first_run_initializes_timestamp_emits_nothing(handler_with_async_callback):
    """Test first run initializes timestamp and emits nothing."""
    handler = handler_with_async_callback
    rss_name = "test_feed"

    log_path = handler.config.rsslog_dir / f"{rss_name}.txt"
    assert not log_path.exists()

    result = handler._read_last_timestamp(rss_name)

    assert result is None
    assert log_path.exists()
    content = log_path.read_text().strip()
    assert 'T' in content


def test_subsequent_run_reads_existing_timestamp(handler_with_async_callback):
    """Test subsequent run reads existing timestamp."""
    handler = handler_with_async_callback
    rss_name = "test_feed"

    log_path = handler.config.rsslog_dir / f"{rss_name}.txt"
    test_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    log_path.write_text(test_dt.isoformat(), encoding='utf-8')

    result = handler._read_last_timestamp(rss_name)

    assert result is not None
    assert result == test_dt.timestamp()


def test_write_last_ts_updates_file(handler_with_async_callback):
    """Test write timestamp updates file."""
    handler = handler_with_async_callback
    rss_name = "test_feed"

    test_timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()

    handler._write_last_timestamp(rss_name, test_timestamp)

    log_path = handler.config.rsslog_dir / f"{rss_name}.txt"
    assert log_path.exists()

    result = handler._read_last_timestamp(rss_name)
    assert result == test_timestamp


def test_entry_already_seen_skipped(handler_with_async_callback):
    """Test entry with old timestamp is skipped."""
    handler = handler_with_async_callback
    entry = Mock()
    entry.updated_parsed = time.gmtime(1000000)
    entry.title = "Test Entry"
    entry.link = "http://test.com"
    entry.summary = "Test summary"

    last_timestamp = 2000000
    cutoff_timestamp = 0

    message_data, timestamp = asyncio.run(
        handler._process_entry(entry, "http://feed.com", "test_feed", last_timestamp, cutoff_timestamp)
    )

    assert message_data is None


def test_entry_too_old_skipped(handler_with_async_callback):
    """Test entry older than MAX_ENTRY_AGE_DAYS is skipped."""
    handler = handler_with_async_callback
    three_days_ago = time.time() - (3 * 86400)
    entry = Mock()
    entry.updated_parsed = time.gmtime(three_days_ago)
    entry.title = "Old Entry"
    entry.link = "http://test.com"
    entry.summary = "Old summary"

    cutoff_timestamp = time.time() - (handler.MAX_ENTRY_AGE_DAYS * 86400)

    message_data, timestamp = asyncio.run(
        handler._process_entry(entry, "http://feed.com", "test_feed", None, cutoff_timestamp)
    )

    assert message_data is None


def test_entry_new_and_recent_processed(handler_with_async_callback):
    """Test new and recent entry is processed."""
    handler = handler_with_async_callback
    recent_time = time.time() - 3600
    entry = Mock()
    entry.updated_parsed = time.gmtime(recent_time)
    entry.title = "New Entry"
    entry.link = "http://test.com/new"
    entry.summary = "New content"

    cutoff_timestamp = time.time() - (handler.MAX_ENTRY_AGE_DAYS * 86400)

    message_data, timestamp = asyncio.run(
        handler._process_entry(entry, "http://feed.com", "test_feed", None, cutoff_timestamp)
    )

    assert message_data is not None
    assert message_data.source_type == "RSS"
    assert message_data.channel_id == "http://feed.com"
    assert message_data.channel_name == "test_feed"
    assert message_data.username == "RSS"
    assert "New Entry" in message_data.text
    assert "http://test.com/new" in message_data.text
    assert not message_data.has_attachments


def test_extract_entry_timestamp_prefers_updated(handler_with_async_callback):
    """Test timestamp extraction prefers updated_parsed."""
    handler = handler_with_async_callback
    entry = Mock()
    entry.updated_parsed = time.gmtime(2000000)
    entry.published_parsed = time.gmtime(1000000)

    result = handler._extract_entry_timestamp(entry)

    assert result == time.mktime(time.gmtime(2000000))


def test_extract_entry_timestamp_falls_back_to_published(handler_with_async_callback):
    """Test timestamp extraction falls back to published_parsed."""
    handler = handler_with_async_callback
    entry = Mock()
    entry.updated_parsed = None
    entry.published_parsed = time.gmtime(1000000)

    result = handler._extract_entry_timestamp(entry)

    assert result == time.mktime(time.gmtime(1000000))


def test_extract_entry_timestamp_no_timestamp_returns_none(handler_with_async_callback):
    """Test timestamp extraction returns None when no timestamp."""
    handler = handler_with_async_callback
    entry = Mock()
    entry.updated_parsed = None
    entry.published_parsed = None

    result = handler._extract_entry_timestamp(entry)

    assert result is None


def test_strip_html_tags_removes_all_tags(handler_with_async_callback):
    """Test HTML tags are removed."""
    handler = handler_with_async_callback
    html_text = "<p>Hello <b>world</b>! Visit <a href='url'>link</a>.</p>"

    result = handler._strip_html_tags(html_text)

    assert result == "Hello world! Visit link."
    assert '<' not in result
    assert '>' not in result


def test_strip_html_tags_decodes_entities(handler_with_async_callback):
    """Test HTML entities are decoded."""
    handler = handler_with_async_callback
    html_text = "Test &lt;tag&gt; &amp; &quot;quotes&quot; &nbsp;"

    result = handler._strip_html_tags(html_text)

    assert result == "Test <tag> & \"quotes\" \xa0"


def test_strip_html_numeric_entities(handler_with_async_callback):
    """Test numeric HTML entities are decoded."""
    handler = handler_with_async_callback
    html_text = "Test [&#8230;] and &#8211; also &#8217;quote&#8217; &#8220;double&#8221;"

    result = handler._strip_html_tags(html_text)

    expected = "Test […] and – also \u2019quote\u2019 \u201cdouble\u201d"
    assert result == expected
    assert '&#8230;' not in result
    assert '&#8211;' not in result
    assert '&#8217;' not in result
    assert '&#8220;' not in result
    assert '&#8221;' not in result


def test_format_entry_text_truncates_long_summary(handler_with_async_callback):
    """Test long summary is truncated."""
    handler = handler_with_async_callback
    entry = Mock()
    entry.title = "Test Title"
    entry.link = "http://test.com"
    entry.summary = "A" * 1500

    result = handler._format_entry_text(entry)

    assert "A" * 1000 in result
    assert " ..." in result
    assert len(result) < 1500


@patch('feedparser.parse')
def test_feed_parse_error_logged_not_raised(mock_feedparser, handler_with_async_callback):
    """Test feed parse error is logged but not raised."""
    handler = handler_with_async_callback
    mock_feed = Mock()
    mock_feed.bozo = True
    mock_feed.bozo_exception = Exception("Parse error")
    mock_feed.entries = []
    mock_feedparser.return_value = mock_feed

    feed_config = {
        'rss_url': 'http://test.com/feed',
        'rss_name': 'test_feed'
    }

    async def run_one_iteration():
        handler._read_last_timestamp('test_feed')

        original_sleep = handler._sleep
        call_count = 0

        async def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()
            await original_sleep(0.01)

        handler._sleep = mock_sleep

        try:
            await handler.run_feed(feed_config)
        except asyncio.CancelledError:
            pass

    asyncio.run(run_one_iteration())


@patch('feedparser.parse')
def test_poll_interval_respected(mock_feedparser, handler_with_async_callback):
    """Test poll interval is respected."""
    handler = handler_with_async_callback
    mock_feed = Mock()
    mock_feed.bozo = False
    mock_feed.entries = []
    mock_feedparser.return_value = mock_feed

    feed_config = {
        'rss_url': 'http://test.com/feed',
        'rss_name': 'test_feed'
    }

    sleep_durations = []

    async def mock_sleep(seconds):
        sleep_durations.append(seconds)
        raise asyncio.CancelledError()

    handler._sleep = mock_sleep

    async def run_one_iteration():
        try:
            await handler.run_feed(feed_config)
        except asyncio.CancelledError:
            pass

    asyncio.run(run_one_iteration())

    assert len(sleep_durations) == 1
    assert sleep_durations[0] == handler.DEFAULT_POLL_INTERVAL
