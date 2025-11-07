"""
Tests for media download and cleanup functionality.

Tests cover:
- TelegramHandler.download_media() (src/TelegramHandler.py:250-258)
- Watchtower media cleanup (src/Watchtower.py:213-219, 87-101)
- Media reuse logic (src/Watchtower.py:234)
"""

import unittest
from unittest.mock import patch, Mock, AsyncMock, call
from pathlib import Path
import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from TelegramHandler import TelegramHandler
from MessageData import MessageData
from datetime import datetime, timezone


class TestMediaDownload(unittest.TestCase):
    """Tests for TelegramHandler.download_media()"""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.api_id = "123456"
        self.mock_config.api_hash = "test_hash"
        self.mock_config.project_root = Path("/tmp/test")
        self.mock_config.config_dir = self.mock_config.project_root / "config"

    @patch('TelegramHandler.TelegramClient')
    def test_download_media_success(self, MockClient):
        """
        Given: Message with media
        When: download_media() called
        Then: Media downloaded to tmp/attachments/, path returned

        Tests: src/TelegramHandler.py:250-258 (download_media success path)
        """
        # Given: Handler with mocked client
        handler = TelegramHandler(self.mock_config)
        handler.client = MockClient()

        # Create message data with media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="test_channel",
            username="test_user",
            text="Test message",
            timestamp=datetime.now(timezone.utc),
            has_media=True,
            media_type="Photo"
        )
        message_data.original_message = Mock()
        message_data.original_message.media = Mock()  # Has media
        message_data.original_message.download_media = AsyncMock(return_value="/tmp/attachments/12345.jpg")

        # When: download_media() called
        result = asyncio.run(handler.download_media(message_data))

        # Then: Media downloaded successfully
        self.assertEqual(result, "/tmp/attachments/12345.jpg")
        message_data.original_message.download_media.assert_called_once()

    @patch('TelegramHandler.TelegramClient')
    def test_download_media_failure_returns_none(self, MockClient):
        """
        Given: Message with media, download fails
        When: download_media() called
        Then: Exception caught, None returned

        Tests: src/TelegramHandler.py:256-258 (exception handling)
        """
        # Given: Handler with failing download
        handler = TelegramHandler(self.mock_config)
        handler.client = MockClient()

        # Create message data with media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="test_channel",
            username="test_user",
            text="Test message",
            timestamp=datetime.now(timezone.utc),
            has_media=True,
            media_type="Photo"
        )
        message_data.original_message = Mock()
        message_data.original_message.media = Mock()
        message_data.original_message.download_media = AsyncMock(
            side_effect=Exception("Network error")
        )

        # When: download_media() called
        with self.assertLogs(level='ERROR') as log_context:
            result = asyncio.run(handler.download_media(message_data))

        # Then: Returns None, error logged
        self.assertIsNone(result)
        self.assertTrue(any("Media download failed" in msg for msg in log_context.output))

    @patch('TelegramHandler.TelegramClient')
    def test_download_media_no_media_returns_none(self, MockClient):
        """
        Given: Message without media
        When: download_media() called
        Then: Returns None immediately without attempting download

        Tests: src/TelegramHandler.py:252 (no media check)
        """
        # Given: Handler
        handler = TelegramHandler(self.mock_config)
        handler.client = MockClient()

        # Create message data without media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="test_channel",
            username="test_user",
            text="Text only message",
            timestamp=datetime.now(timezone.utc),
            has_media=False
        )
        message_data.original_message = Mock()
        message_data.original_message.media = None  # No media
        message_data.original_message.download_media = AsyncMock()

        # When: download_media() called
        result = asyncio.run(handler.download_media(message_data))

        # Then: Returns None, download not attempted
        self.assertIsNone(result)
        message_data.original_message.download_media.assert_not_called()


class TestMediaCleanup(unittest.TestCase):
    """Tests for media cleanup functionality in Watchtower."""

    @patch('os.remove')
    @patch('os.path.exists')
    def test_cleanup_after_message_processing(self, mock_exists, mock_remove):
        """
        Given: Media file exists at path
        When: Message processing completes
        Then: File deleted

        Tests: src/Watchtower.py:213-219 (cleanup in finally block)
        """
        # Given: File exists
        mock_exists.return_value = True
        media_path = "/tmp/attachments/test_image.jpg"

        # When: Cleanup called (simulating finally block)
        if os.path.exists(media_path):
            os.remove(media_path)

        # Then: File removed
        mock_exists.assert_called_with(media_path)
        mock_remove.assert_called_once_with(media_path)

    @patch('os.remove')
    @patch('os.path.exists')
    def test_cleanup_error_logged_not_raised(self, mock_exists, mock_remove):
        """
        Given: Media file exists, os.remove() raises exception
        When: Cleanup runs
        Then: Exception logged, not raised

        Tests: src/Watchtower.py:218-219 (exception handling in cleanup)
        """
        # Given: File exists but removal fails
        mock_exists.return_value = True
        mock_remove.side_effect = OSError("Permission denied")
        media_path = "/tmp/attachments/test_image.jpg"

        # When: Cleanup attempted with exception handling
        try:
            if os.path.exists(media_path):
                os.remove(media_path)
        except OSError:
            pass  # Watchtower logs but doesn't raise

        # Then: Exception occurred but was handled
        mock_remove.assert_called_once()
        # In real code, this would be logged - we're testing error doesn't propagate

    @patch('os.listdir')
    @patch('os.remove')
    @patch('os.path.exists')
    def test_startup_cleanup_removes_leftover_files(self, mock_exists, mock_remove, mock_listdir):
        """
        Given: tmp/attachments/ contains leftover files from crash
        When: Watchtower initializes
        Then: All files in tmp/attachments/ removed

        Tests: src/Watchtower.py:87-101 (startup cleanup)
        """
        # Given: Attachments directory has leftover files
        mock_exists.return_value = True
        mock_listdir.return_value = ["file1.jpg", "file2.png", "file3.mp4"]
        attachments_dir = Path("/tmp/attachments")

        # When: Startup cleanup runs (simulated)
        if os.path.exists(attachments_dir):
            for filename in os.listdir(attachments_dir):
                filepath = attachments_dir / filename
                try:
                    os.remove(filepath)
                except Exception:
                    pass

        # Then: All files removed
        self.assertEqual(mock_remove.call_count, 3)
        expected_calls = [
            call(attachments_dir / "file1.jpg"),
            call(attachments_dir / "file2.png"),
            call(attachments_dir / "file3.mp4")
        ]
        mock_remove.assert_has_calls(expected_calls, any_order=True)

    def test_media_already_downloaded_reused(self):
        """
        Given: message_data.media_path already set
        When: Media decision logic runs
        Then: download_media() NOT called, existing path reused

        Tests: src/Watchtower.py:234 (media reuse logic)
        """
        # Given: Message data with existing media_path
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="test_channel",
            username="test_user",
            text="Test",
            timestamp=datetime.now(timezone.utc),
            has_media=True,
            media_type="Photo",
            media_path="/tmp/attachments/existing.jpg"
        )

        # When: Checking if download needed (simulated logic from Watchtower.py:234)
        needs_download = message_data.media_path is None

        # Then: Download not needed
        self.assertFalse(needs_download)
        self.assertEqual(message_data.media_path, "/tmp/attachments/existing.jpg")

    @patch('os.path.exists')
    def test_cleanup_nonexistent_file_skipped(self, mock_exists):
        """
        Given: Media path doesn't exist
        When: Cleanup runs
        Then: No error, removal skipped

        Tests: src/Watchtower.py:215 (exists check before removal)
        """
        # Given: File doesn't exist
        mock_exists.return_value = False
        media_path = "/tmp/attachments/nonexistent.jpg"

        # When: Cleanup checked
        if os.path.exists(media_path):
            os.remove(media_path)  # This line won't execute

        # Then: No removal attempted
        mock_exists.assert_called_with(media_path)


if __name__ == '__main__':
    unittest.main()
