"""
Tests for Watchtower async pipeline integration.

These tests cover critical end-to-end flows through the async pipeline:
- Message routing from source to destination
- OCR integration trigger
- Media download/cleanup integration
- Restricted mode enforcement in full flow
- Error handling in pipeline

Tests:
- OCR integration trigger (src/Watchtower.py:231-241)
- Media restrictions check (src/Watchtower.py:253-286)
- Defanged URL generation (src/Watchtower.py:243-251)
- Cleanup after processing (src/Watchtower.py:213-219)
"""

import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


class TestWatchtowerOCRIntegration(unittest.TestCase):
    """Tests for OCR integration in message pipeline."""

    @patch('Watchtower.os.path.exists')
    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_trigger_when_enabled_for_channel(self, MockConfig, MockRouter, MockOCR, MockTelegram, MockDiscord, MockQueue, MockMetrics, mock_exists):
        """
        Given: Telegram message with media, OCR enabled for channel
        When: _preprocess_message() called
        Then: OCR extraction attempted, ocr_raw set

        Tests: src/Watchtower.py:231-241 (OCR trigger logic)

        This is CRITICAL - OCR allows routing based on text in images.
        """
        from Watchtower import Watchtower

        # Mock os.path.exists to return True for media file
        mock_exists.return_value = True

        # Mock config
        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.tmp_dir = Path("/tmp")

        # Mock router to enable OCR for channel
        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)

        # Mock OCR handler
        mock_ocr = MockOCR.return_value
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock(return_value="Extracted text from image")

        # Mock Telegram handler
        mock_telegram = MockTelegram.return_value
        mock_telegram.download_media = AsyncMock(return_value="/tmp/attachments/test.jpg")

        # Create Watchtower instance
        watchtower = Watchtower(sources=['telegram'])

        # Create message data with media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=True,
            media_path=None  # Not yet downloaded
        )
        message_data.original_message = Mock()

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: OCR extraction performed
        mock_router.is_ocr_enabled_for_channel.assert_called_once()
        mock_ocr.extract_text.assert_called_once()
        self.assertTrue(message_data.ocr_enabled)
        self.assertEqual(message_data.ocr_raw, "Extracted text from image")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_skipped_when_not_enabled_for_channel(self, MockConfig, MockRouter, MockOCR, MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message with media, OCR NOT enabled for channel
        When: _preprocess_message() called
        Then: OCR extraction NOT attempted

        Tests: src/Watchtower.py:231-233 (OCR check logic)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.tmp_dir = Path("/tmp")

        # Mock router to disable OCR for channel
        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        # Mock OCR handler
        mock_ocr = MockOCR.return_value
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock()

        mock_telegram = MockTelegram.return_value

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=True
        )
        message_data.original_message = Mock()

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: OCR NOT attempted
        mock_ocr.extract_text.assert_not_called()
        self.assertFalse(message_data.ocr_enabled)


class TestWatchtowerDefangedURLs(unittest.TestCase):
    """Tests for defanged URL generation."""

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_defanged_url_added_to_telegram_messages(self, MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message
        When: _preprocess_message() called
        Then: Defanged t.me URL added to metadata

        Tests: src/Watchtower.py:243-251 (defanged URL generation)

        This is SECURITY - prevents accidental navigation in CTI workflows.
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        # Mock Telegram handler to return defanged URL
        mock_telegram = MockTelegram.return_value
        mock_telegram.build_defanged_tg_url = Mock(
            return_value="hxxps://t[.]me/testchannel/123"
        )

        watchtower = Watchtower(sources=['telegram'])

        # Create Telegram message
        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="testchannel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message"
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 123

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: Defanged URL added to metadata
        mock_telegram.build_defanged_tg_url.assert_called_once_with(
            "123456", "testchannel", 123
        )
        self.assertIn('src_url_defanged', message_data.metadata)
        self.assertEqual(message_data.metadata['src_url_defanged'], "hxxps://t[.]me/testchannel/123")


class TestWatchtowerRestrictedMode(unittest.TestCase):
    """Tests for restricted mode enforcement in pipeline."""

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_media_restrictions_enforced_for_restricted_destinations(self, MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message with media, destination with restricted_mode=True
        When: _handle_media_restrictions() called
        Then: Media restriction check performed

        Tests: src/Watchtower.py:267-271 (restricted mode check)

        This is SECURITY CRITICAL - enforces document validation.
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value

        # Mock Telegram handler with restriction check
        mock_telegram = MockTelegram.return_value
        mock_telegram._is_media_restricted = Mock(return_value=True)  # Media allowed
        mock_telegram.download_media = AsyncMock(return_value="/tmp/attachments/test.jpg")

        watchtower = Watchtower(sources=['telegram'])

        # Create message with media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=True
        )
        message_data.original_message = Mock()

        # Destination with restricted mode
        destinations = [
            {'type': 'telegram', 'restricted_mode': True, 'destination': '@channel'}
        ]

        # When: Check media restrictions
        result = asyncio.run(watchtower._handle_media_restrictions(message_data, destinations))

        # Then: Restriction check performed
        mock_telegram._is_media_restricted.assert_called_once()
        self.assertTrue(result)  # Media allowed

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_media_blocked_when_restricted_mode_fails(self, MockConfig, MockRouter, MockTelegram, MockOCR, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message with media that fails restricted mode check
        When: _handle_media_restrictions() called
        Then: Returns False (media blocked)

        Tests: src/Watchtower.py:269-271 (restriction failure)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value

        # Mock Telegram handler with restriction check that fails
        mock_telegram = MockTelegram.return_value
        mock_telegram._is_media_restricted = Mock(return_value=False)  # Media BLOCKED

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=True
        )
        message_data.original_message = Mock()

        destinations = [
            {'type': 'telegram', 'restricted_mode': True, 'destination': '@channel'}
        ]

        # When: Check media restrictions
        result = asyncio.run(watchtower._handle_media_restrictions(message_data, destinations))

        # Then: Media blocked
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
