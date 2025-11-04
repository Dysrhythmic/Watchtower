import unittest
import sys
import os
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


class TestMessageData(unittest.TestCase):
    """Test MessageData dataclass."""

    def test_create_from_telegram(self):
        """Test creating MessageData from Telegram source."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test message"
        )

        self.assertEqual(msg.source_type, "telegram")
        self.assertEqual(msg.channel_id, "@test")
        self.assertEqual(msg.text, "Test message")

    def test_create_from_rss(self):
        """Test creating MessageData from RSS source."""
        msg = MessageData(
            source_type="rss",
            channel_id="https://example.com/feed.xml",
            channel_name="RSS Feed",
            username="RSS",
            timestamp=datetime.now(timezone.utc),
            text="Feed entry"
        )

        self.assertEqual(msg.source_type, "rss")
        self.assertEqual(msg.username, "RSS")

    def test_store_metadata(self):
        """Test metadata dictionary storage."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc)
        )

        msg.metadata['src_url_defanged'] = "hxxps://t[.]me/test/123"
        self.assertEqual(msg.metadata['src_url_defanged'], "hxxps://t[.]me/test/123")

    def test_optional_fields_defaults(self):
        """Test optional fields have defaults."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc)
        )

        self.assertEqual(msg.text, "")
        self.assertFalse(msg.has_media)
        self.assertIsNone(msg.media_type)

    def test_metadata_defaults_empty_dict(self):
        """Test metadata defaults to empty dict."""
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc)
        )

        self.assertIsInstance(msg.metadata, dict)
        self.assertEqual(len(msg.metadata), 0)

    def test_timestamp_timezone_aware(self):
        """Test timestamp is timezone-aware."""
        timestamp = datetime.now(timezone.utc)
        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=timestamp
        )

        self.assertIsNotNone(msg.timestamp.tzinfo)


if __name__ == '__main__':
    unittest.main()
