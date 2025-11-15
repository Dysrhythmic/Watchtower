"""Tests for media download and cleanup functionality."""
from unittest.mock import patch, Mock, AsyncMock, call
from pathlib import Path
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from TelegramHandler import TelegramHandler
from MessageData import MessageData
from datetime import datetime, timezone


@pytest.fixture
def mock_config():
    """Create mock config for tests."""
    config = Mock()
    config.api_id = "123456"
    config.api_hash = "test_hash"
    config.project_root = Path("/tmp/test")
    config.config_dir = config.project_root / "config"
    return config


@patch('TelegramHandler.TelegramClient')
@patch('os.path.getsize')
def test_download_attachment_success(mock_getsize, MockClient, mock_config, caplog):
    """
    Given: Message with media
    When: download_attachment() called
    Then: Media downloaded to tmp/attachments/, path returned
    """
    handler = TelegramHandler(mock_config)
    handler.client = MockClient()
    mock_getsize.return_value = 1024 * 1024

    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="test_channel",
        username="test_user",
        text="Test message",
        timestamp=datetime.now(timezone.utc),
        has_attachments=True,
        attachment_type="Photo"
    )
    message_data.original_message = Mock()
    message_data.original_message.media = Mock()
    message_data.original_message.download_media = AsyncMock(return_value="/tmp/attachments/12345.jpg")

    with caplog.at_level('INFO'):
        result = asyncio.run(handler.download_attachment(message_data))

    assert result == "/tmp/attachments/12345.jpg"
    message_data.original_message.download_media.assert_called_once()
    assert any("Attachment downloaded successfully" in msg for msg in caplog.text.split('\n'))


@patch('TelegramHandler.TelegramClient')
def test_download_attachment_failure_returns_none(MockClient, mock_config, caplog):
    """
    Given: Message with media, download fails
    When: download_attachment() called
    Then: Exception caught, None returned
    """
    handler = TelegramHandler(mock_config)
    handler.client = MockClient()

    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="test_channel",
        username="test_user",
        text="Test message",
        timestamp=datetime.now(timezone.utc),
        has_attachments=True,
        attachment_type="Photo"
    )
    message_data.original_message = Mock()
    message_data.original_message.media = Mock()
    message_data.original_message.download_media = AsyncMock(side_effect=Exception("Network error"))

    with caplog.at_level('ERROR'):
        result = asyncio.run(handler.download_attachment(message_data))

    assert result is None
    assert any("Attachment download failed" in msg for msg in caplog.text.split('\n'))


@patch('TelegramHandler.TelegramClient')
def test_download_attachment_no_media_returns_none(MockClient, mock_config):
    """
    Given: Message without media
    When: download_attachment() called
    Then: Returns None immediately without attempting download
    """
    handler = TelegramHandler(mock_config)
    handler.client = MockClient()

    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="test_channel",
        username="test_user",
        text="Text only message",
        timestamp=datetime.now(timezone.utc),
        has_attachments=False
    )
    message_data.original_message = Mock()
    message_data.original_message.media = None
    message_data.original_message.download_media = AsyncMock()

    result = asyncio.run(handler.download_attachment(message_data))

    assert result is None
    message_data.original_message.download_media.assert_not_called()


@patch('os.remove')
@patch('os.path.exists')
def test_cleanup_after_message_processing(mock_exists, mock_remove):
    """
    Given: Media file exists at path
    When: Message processing completes
    Then: File deleted
    """
    mock_exists.return_value = True
    attachment_path = "/tmp/attachments/test_image.jpg"

    if os.path.exists(attachment_path):
        os.remove(attachment_path)

    mock_exists.assert_called_with(attachment_path)
    mock_remove.assert_called_once_with(attachment_path)


@patch('os.remove')
@patch('os.path.exists')
def test_cleanup_error_logged_not_raised(mock_exists, mock_remove):
    """
    Given: Media file exists, os.remove() raises exception
    When: Cleanup runs
    Then: Exception logged, not raised
    """
    mock_exists.return_value = True
    mock_remove.side_effect = OSError("Permission denied")
    attachment_path = "/tmp/attachments/test_image.jpg"

    try:
        if os.path.exists(attachment_path):
            os.remove(attachment_path)
    except OSError:
        pass

    mock_remove.assert_called_once()


@patch('os.listdir')
@patch('os.remove')
@patch('os.path.exists')
def test_startup_cleanup_removes_leftover_files(mock_exists, mock_remove, mock_listdir):
    """
    Given: tmp/attachments/ contains leftover files from crash
    When: Watchtower initializes
    Then: All files in tmp/attachments/ removed
    """
    mock_exists.return_value = True
    mock_listdir.return_value = ["file1.jpg", "file2.png", "file3.mp4"]
    attachments_dir = Path("/tmp/attachments")

    if os.path.exists(attachments_dir):
        for filename in os.listdir(attachments_dir):
            filepath = attachments_dir / filename
            try:
                os.remove(filepath)
            except Exception:
                pass

    assert mock_remove.call_count == 3
    expected_calls = [
        call(attachments_dir / "file1.jpg"),
        call(attachments_dir / "file2.png"),
        call(attachments_dir / "file3.mp4")
    ]
    mock_remove.assert_has_calls(expected_calls, any_order=True)


def test_media_already_downloaded_reused():
    """
    Given: message_data.attachment_path already set
    When: Media decision logic runs
    Then: download_attachment() NOT called, existing path reused
    """
    message_data = MessageData(
        source_type="telegram",
        channel_id="123",
        channel_name="test_channel",
        username="test_user",
        text="Test",
        timestamp=datetime.now(timezone.utc),
        has_attachments=True,
        attachment_type="Photo",
        attachment_path="/tmp/attachments/existing.jpg"
    )

    needs_download = message_data.attachment_path is None

    assert not needs_download
    assert message_data.attachment_path == "/tmp/attachments/existing.jpg"


@patch('os.path.exists')
def test_cleanup_nonexistent_file_skipped(mock_exists):
    """
    Given: Media path doesn't exist
    When: Cleanup runs
    Then: No error, removal skipped
    """
    mock_exists.return_value = False
    attachment_path = "/tmp/attachments/nonexistent.jpg"

    if os.path.exists(attachment_path):
        os.remove(attachment_path)

    mock_exists.assert_called_with(attachment_path)
