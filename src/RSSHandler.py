import logging
import time
import asyncio
import re
import feedparser
from datetime import datetime, timezone
from typing import Callable, Dict, Any, Optional
from MessageData import MessageData
from ConfigManager import ConfigManager

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class RSSHandler:
    """Polls RSS/Atom feeds and emits MessageData for new items.

    MAX_ENTRY_AGE_DAYS prevents message floods after extended downtime by ignoring
    entries older than 2 days. Without this, restarting after a week offline would
    route hundreds of old messages that users have already seen elsewhere.

    DEFAULT_POLL_INTERVAL is the fixed polling interval for all RSS feeds.
    All feeds are polled every 5 minutes regardless of configuration.
    """
    MAX_ENTRY_AGE_DAYS = 2
    DEFAULT_POLL_INTERVAL = 300  # seconds (5 minutes)

    def __init__(self, config: ConfigManager, on_message: Callable[[MessageData, bool], Any]):
        self.config = config
        self.on_message = on_message
        self._running = False

    def _log_path(self, rss_name: str):
        return self.config.rsslog_dir / f"{rss_name}.txt"

    def _read_last_ts(self, rss_name: str) -> Optional[float]:
        log_file_path = self._log_path(rss_name)
        if not log_file_path.exists():
            # Create with current time and emit nothing on first run
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

    def _write_last_ts(self, rss_name: str, timestamp: float):
        log_file_path = self._log_path(rss_name)
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        log_file_path.write_text(dt, encoding='utf-8')

    def _extract_entry_timestamp(self, entry) -> Optional[float]:
        """Extract timestamp from RSS entry (prefers updated, then published)."""
        for key in ('updated_parsed', 'published_parsed'):
            val = getattr(entry, key, None)
            if val:
                return time.mktime(val)
        return None

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """Strip all HTML tags from text using regex.

        Feedparser sanitizes HTML by default (removes dangerous tags like <script>)
        but keeps safe tags like <a>, <p>, <b>. This method completely removes all
        remaining HTML tags for clean text output.
        """
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode common HTML entities
        text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        return text

    def _format_entry_text(self, entry) -> str:
        """Format RSS entry into message text.

        Feedparser sanitizes HTML by default (keeps safe tags, removes dangerous ones).
        This method strips all remaining HTML tags for clean text output.
        """
        title = getattr(entry, 'title', '') or ''
        link = getattr(entry, 'link', '') or ''
        summary = getattr(entry, 'summary', '') or ''

        # Strip HTML tags from title and summary
        title = self._strip_html_tags(title)
        summary = self._strip_html_tags(summary)

        if len(summary) > 1000:
            summary = summary[:1000] + " ..."

        return "\n".join(s for s in [title, link, summary] if s)

    async def _process_entry(self, entry, rss_url: str, rss_name: str, last_timestamp: Optional[float], cutoff_timestamp: float) -> tuple[Optional[MessageData], Optional[float]]:
        """Process a single RSS entry.

        Returns:
            tuple: (MessageData if entry should be routed, entry timestamp)
        """
        timestamp = self._extract_entry_timestamp(entry)
        if timestamp is None:
            return None, None

        if timestamp < cutoff_timestamp:
            return None, None

        if last_timestamp is not None and timestamp <= last_timestamp:
            return None, None

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

    async def run_feed(self, feed: Dict[str, Any]):
        """Run a single feed loop forever.

        Polls the feed every DEFAULT_POLL_INTERVAL seconds (300s / 5 minutes).
        The interval_sec config parameter is ignored for consistency and simplicity.
        """
        rss_url = feed['rss_url']
        rss_name = feed['rss_name']

        last_timestamp = self._read_last_ts(rss_name)
        newest_seen = last_timestamp or 0.0

        while True:
            try:
                parsed_feed = feedparser.parse(rss_url)
                if parsed_feed.bozo:
                    logger.error(f"[RSSHandler] Parse error for {rss_name}: {getattr(parsed_feed, 'bozo_exception', '')}")

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

    async def _sleep(self, seconds: int):
        # small sleep
        await asyncio.sleep(seconds)
