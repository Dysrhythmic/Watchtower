"""Test MessageData generic message container dataclass."""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


def test_create_from_telegram():
    """Test creating MessageData from Telegram source."""
    msg = MessageData(
        source_type="telegram",
        channel_id="@test",
        channel_name="Test Channel",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Test message"
    )

    assert msg.source_type == "telegram"
    assert msg.channel_id == "@test"
    assert msg.text == "Test message"


def test_create_from_rss():
    """Test creating MessageData from RSS source."""
    msg = MessageData(
        source_type="rss",
        channel_id="https://example.com/feed.xml",
        channel_name="RSS Feed",
        username="RSS",
        timestamp=datetime.now(timezone.utc),
        text="Feed entry"
    )

    assert msg.source_type == "rss"
    assert msg.username == "RSS"


def test_store_metadata():
    """Test metadata dictionary storage."""
    msg = MessageData(
        source_type="telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc)
    )

    msg.metadata['src_url_defanged'] = "hxxps://t[.]me/test/123"
    assert msg.metadata['src_url_defanged'] == "hxxps://t[.]me/test/123"


def test_optional_fields_defaults():
    """Test optional fields have defaults."""
    msg = MessageData(
        source_type="telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc)
    )

    assert msg.text == ""
    assert not msg.has_attachments
    assert msg.attachment_type is None


def test_metadata_defaults_empty_dict():
    """Test metadata defaults to empty dict."""
    msg = MessageData(
        source_type="telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=datetime.now(timezone.utc)
    )

    assert isinstance(msg.metadata, dict)
    assert len(msg.metadata) == 0


def test_timestamp_timezone_aware():
    """Test timestamp is timezone-aware."""
    timestamp = datetime.now(timezone.utc)
    msg = MessageData(
        source_type="telegram",
        channel_id="@test",
        channel_name="Test",
        username="@user",
        timestamp=timestamp
    )

    assert msg.timestamp.tzinfo is not None
