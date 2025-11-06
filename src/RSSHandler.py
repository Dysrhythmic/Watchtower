"""
RSSHandler - RSS/Atom feed monitoring and message generation

This module polls RSS and Atom feeds at regular intervals and converts new entries
into MessageData objects for routing. Handles feed parsing, timestamp tracking to
avoid duplicate processing, and age filtering to prevent message floods.

Features:
- Automatic polling at 5-minute intervals
- Timestamp persistence to track processed entries
- Age-based filtering (2-day cutoff) to prevent floods after downtime
- HTML tag stripping and entity decoding for clean text
- Per-feed state tracking via filesystem logs

Age Filtering Logic:
    When the application restarts after extended downtime (e.g., 1 week offline),
    RSS feeds may contain hundreds of old entries. Without age filtering, all these
    would be routed as "new" messages, flooding destinations with content users have
    already seen elsewhere. MAX_ENTRY_AGE_DAYS (2 days) prevents this by ignoring
    entries older than the cutoff.

Polling Strategy:
    All feeds are polled every 5 minutes (DEFAULT_POLL_INTERVAL = 300 seconds).
    This is a fixed interval for consistency and simplicity. Per-feed custom
    intervals are not currently supported.
"""
import time
import asyncio
import re
import html
import feedparser
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional
from pathlib import Path
from logger_setup import setup_logger
from MessageData import MessageData
from ConfigManager import ConfigManager

logger = setup_logger(__name__)


class RSSHandler:
    """Polls RSS/Atom feeds and emits MessageData for new items.

    Maintains per-feed timestamp logs to avoid reprocessing entries. Uses age-based
    filtering to prevent message floods after extended application downtime.
    """
    MAX_ENTRY_AGE_DAYS = 2  # Ignore entries older than 2 days
    DEFAULT_POLL_INTERVAL = 300  # Poll every 5 minutes (seconds)

    def __init__(self, config: ConfigManager, on_message: Callable[[MessageData, bool], Any]):
        """Initialize RSS handler with configuration and message callback.

        Args:
            config: ConfigManager instance providing feed list and log directory
            on_message: Async callback function to route new RSS entries
                        Signature: async def on_message(MessageData, is_latest: bool) -> bool
        """
        self.config = config
        self.on_message = on_message
        self._running = False

    def _log_path(self, rss_name: str) -> Path:
        """Get the path to the RSS feed's timestamp log file.

        Each feed has a log file storing the timestamp of the last processed entry.
        Format: {rss_name}.txt containing ISO 8601 timestamp.

        Args:
            rss_name: Name of the RSS feed

        Returns:
            Path: Path object for the RSS feed's log file
        """
        return self.config.rsslog_dir / f"{rss_name}.txt"

    def _read_last_ts(self, rss_name: str) -> Optional[float]:
        """Read the last processed timestamp for an RSS feed.

        On first run (log file doesn't exist), initializes the log with current time
        and returns None to signal that no entries should be processed yet. This
        prevents flooding with all historical entries on initial startup.

        Args:
            rss_name: Name of the RSS feed

        Returns:
            Optional[float]: Unix timestamp of last processed entry, or None if:
                - Feed is being tracked for the first time
                - Log file is empty or corrupted
        """
        log_file_path = self._log_path(rss_name)
        if not log_file_path.exists():
            # Initialize log with current time - process only entries newer than now
            now = datetime.now(timezone.utc).isoformat()
            log_file_path.write_text(now, encoding='utf-8')
            logger.info(f"[RSSHandler] {rss_name} initialized")
            return None
        try:
            content = log_file_path.read_text(encoding='utf-8').strip()
            if not content:
                return None
            dt = datetime.fromisoformat(content)
            return dt.timestamp()
        except Exception:
            return None

    def _write_last_ts(self, rss_name: str, timestamp: float) -> None:
        """Write the last processed timestamp for an RSS feed.

        Stores timestamp in ISO 8601 format for human readability.

        Args:
            rss_name: Name of the RSS feed
            timestamp: Unix timestamp to save
        """
        log_file_path = self._log_path(rss_name)
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        log_file_path.write_text(dt, encoding='utf-8')

    def _extract_entry_timestamp(self, entry) -> Optional[float]:
        """Extract timestamp from RSS entry.

        Tries 'updated_parsed' first (modification time), falls back to
        'published_parsed' (original publication time). Returns None if neither exists.

        Args:
            entry: Feedparser entry object

        Returns:
            Optional[float]: Unix timestamp, or None if no date fields found
        """
        for key in ('updated_parsed', 'published_parsed'):
            val = getattr(entry, key, None)
            if val:
                return time.mktime(val)
        return None

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """Strip all HTML tags from text using regex and decode HTML entities.

        Feedparser sanitizes HTML by default (removes dangerous tags like <script>)
        but keeps safe tags like <a>, <p>, <b>. This method completely removes all
        remaining HTML tags and decodes entities for clean text output.

        Args:
            text: Text potentially containing HTML tags and entities

        Returns:
            str: Clean text with tags removed and entities decoded

        Example:
            >>> _strip_html_tags("<p>Breaking: &#8220;New CVE&#8221; found</p>")
            'Breaking: "New CVE" found'
        """
        # Remove all HTML tags with regex
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities: &#8230; (ellipsis), &quot; (quote), etc.
        text = html.unescape(text)
        return text

    def _format_entry_text(self, entry) -> str:
        """Format RSS entry into message text with title, link, and summary.

        Extracts entry fields and strips HTML tags for clean text. Truncates
        summaries longer than 1000 characters.

        Args:
            entry: Feedparser entry object

        Returns:
            str: Formatted message text with title, link, and summary (newline-separated)
        """
        title = getattr(entry, 'title', '') or ''
        link = getattr(entry, 'link', '') or ''
        summary = getattr(entry, 'summary', '') or ''

        # Strip HTML tags from title and summary
        title = self._strip_html_tags(title)
        summary = self._strip_html_tags(summary)

        # Truncate long summaries for readability
        if len(summary) > 1000:
            summary = summary[:1000] + " ..."

        # Join non-empty fields with newlines
        return "\n".join(s for s in [title, link, summary] if s)

    async def _process_entry(self, entry, rss_url: str, rss_name: str, last_timestamp: Optional[float], cutoff_timestamp: float) -> tuple[Optional[MessageData], Optional[float]]:
        """Process a single RSS entry and convert to MessageData if new.

        Applies three filters:
        1. Must have a valid timestamp
        2. Must be newer than cutoff (not too old)
        3. Must be newer than last processed timestamp (not a duplicate)

        Args:
            entry: Feedparser entry object
            rss_url: RSS feed URL (used as channel_id)
            rss_name: Human-readable feed name
            last_timestamp: Last processed timestamp for this feed (None on first run)
            cutoff_timestamp: Entries older than this are ignored (age filter)

        Returns:
            tuple[Optional[MessageData], Optional[float]]:
                - MessageData if entry should be routed, None if filtered out
                - Entry timestamp (for tracking newest seen), None if no timestamp
        """
        timestamp = self._extract_entry_timestamp(entry)
        if timestamp is None:
            return None, None

        # Filter 1: Too old (beyond MAX_ENTRY_AGE_DAYS)
        if timestamp < cutoff_timestamp:
            return None, None

        # Filter 2: Already processed (timestamp <= last seen)
        if last_timestamp is not None and timestamp <= last_timestamp:
            return None, None

        # Entry passed all filters - create MessageData
        text = self._format_entry_text(entry)

        message_data = MessageData(
            source_type="rss",
            channel_id=rss_url,
            channel_name=rss_name,
            username="RSS",
            timestamp=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            text=text,
            has_media=False
        )

        return message_data, timestamp

    async def run_feed(self, feed: Dict[str, Any]) -> None:
        """Run a single feed loop forever.

        Continuously polls the feed at DEFAULT_POLL_INTERVAL (5 minutes). On each poll:
        1. Parse feed XML/JSON
        2. Process each entry (filter by age and duplication)
        3. Route new entries via on_message callback
        4. Update last_timestamp log

        Args:
            feed: Feed configuration dict with 'rss_url' and 'rss_name' keys
        """
        rss_url = feed['rss_url']
        rss_name = feed['rss_name']

        last_timestamp = self._read_last_ts(rss_name)
        newest_seen = last_timestamp or 0.0

        while True:
            try:
                parsed_feed = feedparser.parse(rss_url)
                if parsed_feed.bozo:
                    logger.warning(f"[RSSHandler] Parse error for {rss_name}: {getattr(parsed_feed, 'bozo_exception', '')}")

                count_new = 0
                count_routed = 0
                count_too_old = 0

                cutoff_timestamp = time.time() - (self.MAX_ENTRY_AGE_DAYS * 86400)

                for entry in parsed_feed.entries:
                    message_data, timestamp = await self._process_entry(entry, rss_url, rss_name, last_timestamp, cutoff_timestamp)

                    if message_data is None:
                        if timestamp is None:
                            continue
                        if timestamp < cutoff_timestamp:
                            count_too_old += 1
                        continue

                    count_new += 1
                    routed_successfully = await self.on_message(message_data, is_latest=False)
                    if routed_successfully:
                        count_routed += 1
                    newest_seen = max(newest_seen, timestamp)

                if newest_seen and (last_timestamp is None or newest_seen > last_timestamp):
                    self._write_last_ts(rss_name, newest_seen)
                    last_timestamp = newest_seen

                log_msg = f"[RSSHandler] {rss_name} polled; new={count_new}; routed={count_routed}"
                if count_too_old > 0:
                    log_msg += f"; too_old={count_too_old}"
                logger.info(log_msg)

            except Exception as e:
                logger.error(f"[RSSHandler] Poll error for {rss_name}: {e}")

            await self._sleep(self.DEFAULT_POLL_INTERVAL)

    async def _sleep(self, seconds: int) -> None:
        """Sleep for specified duration (used for polling intervals).

        Args:
            seconds: Duration to sleep in seconds
        """
        await asyncio.sleep(seconds)
