"""
Test MessageData - Generic message container dataclass

This module tests the MessageData dataclass which provides a source-agnostic
message representation for cross-platform message handling (Telegram, RSS, etc.).

What This Tests:
    - MessageData creation with required fields
    - Default values for optional fields
    - Metadata dict extensibility
    - OCR fields (ocr_enabled, ocr_raw)
    - Media handling fields (media_path, has_media, media_type)
    - Reply context structure
    - Source type handling (telegram, rss)

Test Pattern - Basic Creation:
    1. Create MessageData with required fields:
       - source_type, channel_id, channel_name
       - username, timestamp, text
    2. Assert all fields populated correctly
    3. Check default values for optional fields
    4. Verify metadata is empty dict by default

Test Pattern - Optional Fields:
    1. Create MessageData with optional fields:
       - has_media, media_type, media_path
       - ocr_enabled, ocr_raw
       - reply_context, original_message
    2. Assert optional fields set correctly
    3. Test None/False defaults

MessageData Structure:
    Required:
        source_type: "telegram" or "rss"
        channel_id: Source channel identifier
        channel_name: Human-readable channel name
        username: Message author
        timestamp: datetime in UTC
        text: Message content

    Optional:
        has_media: bool - Whether message has attachments
        media_type: str - "Photo", "Document", "Other"
        media_path: str - Path to downloaded media file
        ocr_enabled: bool - Whether OCR was used
        ocr_raw: str - Extracted OCR text
        reply_context: dict - Original message being replied to
        original_message: object - Source-specific message object
        metadata: dict - Extensible metadata (src_url_defanged, etc.)

How to Add New Tests:
    1. Add test method starting with test_
    2. Use descriptive docstring: """Test <what MessageData feature>."""
    3. Create MessageData with datetime.now(timezone.utc)
    4. Use self.assertEqual/assertIsNone for field verification
    5. For metadata tests: populate metadata dict and assert keys
"""
import unittest
import sys
import os
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


class TestMessageData(unittest.TestCase):
    """Test MessageData generic message container dataclass."""

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
