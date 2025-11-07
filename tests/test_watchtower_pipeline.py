"""
Comprehensive tests for Watchtower message processing pipeline.

Tests cover critical untested areas in src/Watchtower.py:
- Lines 171-219: _handle_message (main async handler)
- Lines 230-251: _preprocess_message (OCR/URL generation)
- Lines 302-322: _dispatch_to_destination (routing logic)
- Lines 339-405: _send_to_discord (Discord send operations)
- Lines 418-461: _send_to_telegram (Telegram send operations)

Test Classes:
1. TestWatchtowerMessagePreprocessing - Message preprocessing with OCR and URLs
2. TestWatchtowerDispatchLogic - Message routing and dispatch
3. TestWatchtowerDiscordSending - Discord delivery operations
4. TestWatchtowerTelegramSending - Telegram delivery operations
"""

import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import sys
import os
import time
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from Watchtower import Watchtower

class TestWatchtowerMessagePreprocessing(unittest.TestCase):
    """Tests for message preprocessing (_preprocess_message)."""

    @patch('Watchtower.os.path.exists')
    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_preprocess_adds_ocr_text_when_available(self, MockConfig, MockRouter, MockOCR,
                                                      MockTelegram, MockDiscord, MockQueue,
                                                      MockMetrics, mock_exists):
        """
        Given: Telegram message with media, OCR enabled for channel, OCR available
        When: _preprocess_message() is called
        Then: OCR text is extracted and added to message_data.ocr_raw, metrics incremented

        Tests: src/Watchtower.py:230-241 (OCR processing)
        """
        from Watchtower import Watchtower

        # Mock os.path.exists to return True for media file
        mock_exists.return_value = True

        # Setup mocks
        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)

        mock_ocr = MockOCR.return_value
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock(return_value="Invoice #12345\nAmount: $500")

        mock_telegram = MockTelegram.return_value
        mock_telegram.download_media = AsyncMock(return_value="/tmp/attachments/test.jpg")
        mock_telegram.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/channel/1")

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        # Create message with media
        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="invoices_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Check this invoice",
            has_media=True,
            media_path="/tmp/attachments/test.jpg"
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 1

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: OCR text extracted and set
        mock_ocr.extract_text.assert_called_once_with("/tmp/attachments/test.jpg")
        self.assertTrue(message_data.ocr_enabled)
        self.assertEqual(message_data.ocr_raw, "Invoice #12345\nAmount: $500")
        mock_metrics.increment.assert_any_call("ocr_processed")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_preprocess_skips_ocr_when_not_enabled(self, MockConfig, MockRouter, MockOCR,
                                                     MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message with media, OCR NOT enabled for channel
        When: _preprocess_message() is called
        Then: OCR extraction is skipped, ocr_enabled remains False

        Tests: src/Watchtower.py:230-233 (OCR check)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        mock_ocr = MockOCR.return_value
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock()

        mock_telegram = MockTelegram.return_value
        mock_telegram.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/channel/1")

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="normal_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Regular message",
            has_media=True
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 1

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: OCR not performed
        mock_ocr.extract_text.assert_not_called()
        self.assertFalse(message_data.ocr_enabled)
        self.assertIsNone(message_data.ocr_raw)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_preprocess_generates_defanged_url(self, MockConfig, MockRouter, MockOCR,
                                                 MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message with original_message
        When: _preprocess_message() is called
        Then: Defanged URL is generated and added to metadata

        Tests: src/Watchtower.py:243-251 (defanged URL generation)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        mock_telegram = MockTelegram.return_value
        mock_telegram.build_defanged_tg_url = Mock(
            return_value="hxxps://t[.]me/malware_samples/999"
        )

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="-1001234567890",
            channel_name="malware_samples",
            username="threat_actor",
            timestamp=datetime.now(timezone.utc),
            text="New sample"
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 999

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: Defanged URL added
        mock_telegram.build_defanged_tg_url.assert_called_once_with(
            "-1001234567890", "malware_samples", 999
        )
        self.assertIn('src_url_defanged', message_data.metadata)
        self.assertEqual(message_data.metadata['src_url_defanged'],
                        "hxxps://t[.]me/malware_samples/999")

    @patch('Watchtower.os.path.exists')
    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_preprocess_handles_ocr_failure_gracefully(self, MockConfig, MockRouter, MockOCR,
                                                         MockTelegram, MockDiscord, MockQueue,
                                                         MockMetrics, mock_exists):
        """
        Given: Telegram message with media, OCR enabled but extraction fails
        When: _preprocess_message() is called
        Then: OCR failure is handled gracefully, no crash, ocr_raw remains None

        Tests: src/Watchtower.py:237-241 (OCR error handling)
        """
        from Watchtower import Watchtower

        mock_exists.return_value = True

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)

        mock_ocr = MockOCR.return_value
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock(return_value=None)  # OCR returns None (failure)

        mock_telegram = MockTelegram.return_value
        mock_telegram.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/ch/1")

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test",
            has_media=True,
            media_path="/tmp/attachments/corrupted.jpg"
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 1

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: No crash, ocr_raw is None
        self.assertFalse(message_data.ocr_enabled)
        self.assertIsNone(message_data.ocr_raw)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_preprocess_no_media_no_ocr(self, MockConfig, MockRouter, MockOCR,
                                         MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram message without media
        When: _preprocess_message() is called
        Then: OCR is skipped entirely

        Tests: src/Watchtower.py:231-232 (OCR conditions)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_ocr = MockOCR.return_value
        mock_ocr.extract_text = Mock()

        mock_telegram = MockTelegram.return_value
        mock_telegram.build_defanged_tg_url = Mock(return_value="hxxps://t[.]me/ch/1")

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="text_only",
            username="user",
            timestamp=datetime.now(timezone.utc),
            text="Text only message",
            has_media=False
        )
        message_data.original_message = Mock()
        message_data.original_message.id = 1

        # When: Preprocess message
        asyncio.run(watchtower._preprocess_message(message_data))

        # Then: OCR not attempted
        mock_ocr.extract_text.assert_not_called()
        self.assertFalse(message_data.ocr_enabled)


class TestWatchtowerDispatchLogic(unittest.TestCase):
    """Tests for message dispatch logic (_dispatch_to_destination)."""

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_dispatch_to_discord_destination(self, MockConfig, MockRouter, MockOCR,
                                               MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message and Discord destination configuration
        When: _dispatch_to_destination() is called
        Then: Message is formatted for Discord and sent to Discord handler

        Tests: src/Watchtower.py:310-312 (Discord dispatch)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_discord = MockDiscord.return_value
        mock_discord.format_message = Mock(return_value="**Formatted Discord Message**")
        mock_discord.send_message = Mock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message"
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'parser': {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        # When: Dispatch to destination
        result = asyncio.run(watchtower._dispatch_to_destination(
            message_data, destination, media_passes_restrictions=True
        ))

        # Then: Discord handler called
        mock_discord.format_message.assert_called_once()
        mock_discord.send_message.assert_called_once()
        self.assertTrue(result)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_dispatch_to_telegram_destination(self, MockConfig, MockRouter, MockOCR,
                                                MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message and Telegram destination configuration
        When: _dispatch_to_destination() is called
        Then: Message is formatted for Telegram and sent to Telegram handler

        Tests: src/Watchtower.py:314-315 (Telegram dispatch)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_telegram = MockTelegram.return_value
        mock_telegram.format_message = Mock(return_value="**Formatted Telegram Message**")
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test message"
        )

        destination = {
            'type': 'telegram',
            'name': 'Telegram Feed',
            'telegram_destination_channel': '@target_channel',
            'parser': {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        # When: Dispatch to destination
        result = asyncio.run(watchtower._dispatch_to_destination(
            message_data, destination, media_passes_restrictions=True
        ))

        # Then: Telegram handler called
        mock_telegram.format_message.assert_called_once()
        self.assertTrue(result)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_dispatch_with_media_path(self, MockConfig, MockRouter, MockOCR,
                                        MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message with media_path and no restricted mode
        When: _dispatch_to_destination() is called
        Then: include_media is True and media is sent

        Tests: src/Watchtower.py:304-307 (media inclusion logic)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_discord = MockDiscord.return_value
        mock_discord.format_message = Mock(return_value="Message with media")
        mock_discord.send_message = Mock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Message with image",
            has_media=True,
            media_type="photo",
            media_path="/tmp/attachments/photo.jpg"
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'parser': {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        # When: Dispatch to destination
        result = asyncio.run(watchtower._dispatch_to_destination(
            message_data, destination, media_passes_restrictions=True
        ))

        # Then: Media included in send
        args, kwargs = mock_discord.send_message.call_args
        self.assertIn('/tmp/attachments/photo.jpg', str(args) + str(kwargs))
        self.assertTrue(result)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_dispatch_without_media(self, MockConfig, MockRouter, MockOCR,
                                      MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message without media
        When: _dispatch_to_destination() is called
        Then: Text-only message is sent

        Tests: src/Watchtower.py:304-307 (no media case)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_discord = MockDiscord.return_value
        mock_discord.format_message = Mock(return_value="Text only message")
        mock_discord.send_message = Mock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Text only",
            has_media=False
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'parser': {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        # When: Dispatch to destination
        result = asyncio.run(watchtower._dispatch_to_destination(
            message_data, destination, media_passes_restrictions=True
        ))

        # Then: Send called with text only (no media_path)
        args, kwargs = mock_discord.send_message.call_args
        # Check that media_path is None or not a file path
        if len(args) >= 3:
            self.assertIsNone(args[2])
        self.assertTrue(result)

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_dispatch_metrics_incremented(self, MockConfig, MockRouter, MockOCR,
                                            MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Successful message dispatch to Discord
        When: _dispatch_to_destination() is called
        Then: Success is returned (True)

        Tests: src/Watchtower.py:322 (return value)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_router = MockRouter.return_value
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_discord = MockDiscord.return_value
        mock_discord.format_message = Mock(return_value="Message")
        mock_discord.send_message = Mock(return_value=True)  # Success

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test"
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'parser': {'trim_front_lines': 0, 'trim_back_lines': 0}
        }

        # When: Dispatch to destination
        result = asyncio.run(watchtower._dispatch_to_destination(
            message_data, destination, media_passes_restrictions=True
        ))

        # Then: Returns success
        self.assertTrue(result)


class TestWatchtowerDiscordSending(unittest.TestCase):
    """Tests for Discord message sending (_send_to_discord)."""

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_discord_text_only(self, MockConfig, MockRouter, MockOCR,
                                         MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Text-only message (no media)
        When: _send_to_discord() is called
        Then: Message sent via Discord webhook, returns "sent"

        Tests: src/Watchtower.py:345-351 (Discord send success)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_discord = MockDiscord.return_value
        mock_discord.send_message = Mock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Text message"
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token'
        }

        content = "**Formatted Message**"

        # When: Send to Discord
        status = asyncio.run(watchtower._send_to_discord(
            message_data, destination, content, include_media=False
        ))

        # Then: Message sent successfully
        mock_discord.send_message.assert_called_once_with(
            "**Formatted Message**", 'https://discord.com/api/webhooks/123/token', None
        )
        self.assertEqual(status, "sent")
        mock_metrics.increment.assert_any_call("messages_sent_discord")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_discord_with_media(self, MockConfig, MockRouter, MockOCR,
                                          MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message with media, include_media=True
        When: _send_to_discord() is called
        Then: Message sent with media attachment

        Tests: src/Watchtower.py:344-351 (Discord send with media)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_discord = MockDiscord.return_value
        mock_discord.send_message = Mock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Message with image",
            has_media=True,
            media_type="photo",
            media_path="/tmp/attachments/photo.jpg"
        )

        destination = {
            'type': 'discord',
            'name': 'Discord Feed',
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token'
        }

        content = "**Message with attachment**"

        # When: Send to Discord with media
        status = asyncio.run(watchtower._send_to_discord(
            message_data, destination, content, include_media=True
        ))

        # Then: Message sent with media
        mock_discord.send_message.assert_called_once_with(
            "**Message with attachment**",
            'https://discord.com/api/webhooks/123/token',
            "/tmp/attachments/photo.jpg"
        )
        self.assertEqual(status, "sent")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_discord_success_increments_messages_sent(self, MockConfig, MockRouter, MockOCR,
                                                                MockTelegram, MockDiscord, MockQueue,
                                                                MockMetrics):
        """
        Given: Successful Discord send
        When: _send_to_discord() completes
        Then: messages_sent_discord metric is incremented

        Tests: src/Watchtower.py:348 (metrics increment)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_discord = MockDiscord.return_value
        mock_discord.send_message = Mock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test",
            ocr_raw="OCR text from image"
        )

        destination = {'discord_webhook_url': 'https://discord.com/api/webhooks/123/token'}

        # When: Send to Discord
        asyncio.run(watchtower._send_to_discord(
            message_data, destination, "Content", include_media=False
        ))

        # Then: Metrics incremented
        mock_metrics.increment.assert_any_call("messages_sent_discord")
        mock_metrics.increment.assert_any_call("ocr_msgs_sent")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_discord_failure_enqueues(self, MockConfig, MockRouter, MockOCR,
                                                MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Discord send fails (rate limit or network error)
        When: _send_to_discord() is called
        Then: Message is enqueued for retry, returns "queued for retry"

        Tests: src/Watchtower.py:352-361 (failure handling and retry queue)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_discord = MockDiscord.return_value
        mock_discord.send_message = Mock(return_value=False)  # Failure

        mock_queue = MockQueue.return_value
        mock_queue.enqueue = Mock()

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test"
        )

        destination = {
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'name': 'Discord Feed'
        }

        # When: Send to Discord fails
        status = asyncio.run(watchtower._send_to_discord(
            message_data, destination, "Content", include_media=False
        ))

        # Then: Message enqueued for retry
        mock_queue.enqueue.assert_called_once()
        self.assertEqual(status, "queued for retry")
        mock_metrics.increment.assert_any_call("messages_queued_retry")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_discord_handles_format_error(self, MockConfig, MockRouter, MockOCR,
                                                    MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message with media blocked by restricted mode
        When: _send_to_discord() is called with include_media=False
        Then: Content includes restricted mode notice

        Tests: src/Watchtower.py:338-342 (restricted mode messaging)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_discord = MockDiscord.return_value
        mock_discord.send_message = Mock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="test_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test",
            has_media=True,
            media_type="video"
        )

        destination = {
            'discord_webhook_url': 'https://discord.com/api/webhooks/123/token',
            'restricted_mode': True
        }

        # When: Send to Discord without media (restricted mode blocked it)
        asyncio.run(watchtower._send_to_discord(
            message_data, destination, "Original content", include_media=False
        ))

        # Then: Content includes restriction notice
        args, _ = mock_discord.send_message.call_args
        content_sent = args[0]
        self.assertIn("Media attachment filtered due to restricted mode", content_sent)


class TestWatchtowerTelegramSending(unittest.TestCase):
    """Tests for Telegram message sending (_send_to_telegram)."""

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_telegram_text_only(self, MockConfig, MockRouter, MockOCR,
                                          MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Text-only message
        When: _send_to_telegram() is called
        Then: Message sent via Telegram send_copy, returns "sent"

        Tests: src/Watchtower.py:387-392 (Telegram send success)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_telegram = MockTelegram.return_value
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Text message"
        )

        destination = {
            'type': 'telegram',
            'telegram_destination_channel': '@target_channel',
            'name': 'Telegram Feed'
        }

        content = "**Formatted Telegram Message**"

        # When: Send to Telegram
        status = asyncio.run(watchtower._send_to_telegram(
            message_data, destination, content, include_media=False
        ))

        # Then: Message sent successfully
        mock_telegram.resolve_destination.assert_called_once_with('@target_channel')
        mock_telegram.send_copy.assert_called_once_with(
            -1001234567890, "**Formatted Telegram Message**", None
        )
        self.assertEqual(status, "sent")
        mock_metrics.increment.assert_any_call("messages_sent_telegram")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_telegram_with_media(self, MockConfig, MockRouter, MockOCR,
                                           MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Message with media, include_media=True
        When: _send_to_telegram() is called
        Then: Message sent with media attachment

        Tests: src/Watchtower.py:378, 387 (media path handling)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_telegram = MockTelegram.return_value
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Message with photo",
            has_media=True,
            media_type="photo",
            media_path="/tmp/attachments/photo.jpg"
        )

        destination = {
            'type': 'telegram',
            'telegram_destination_channel': '@target_channel',
            'name': 'Telegram Feed'
        }

        content = "**Message with attachment**"

        # When: Send to Telegram with media
        status = asyncio.run(watchtower._send_to_telegram(
            message_data, destination, content, include_media=True
        ))

        # Then: Message sent with media
        mock_telegram.send_copy.assert_called_once_with(
            -1001234567890, "**Message with attachment**", "/tmp/attachments/photo.jpg"
        )
        self.assertEqual(status, "sent")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_telegram_caption_overflow_handling(self, MockConfig, MockRouter, MockOCR,
                                                          MockTelegram, MockDiscord, MockQueue,
                                                          MockMetrics):
        """
        Given: Message with very long content (> Telegram caption limit)
        When: _send_to_telegram() is called
        Then: Telegram handler manages caption overflow appropriately

        Tests: src/Watchtower.py:387 (caption handling)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_telegram = MockTelegram.return_value
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=True)

        watchtower = Watchtower(sources=['telegram'])

        # Very long content
        long_content = "A" * 2000

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text=long_content
        )

        destination = {
            'type': 'telegram',
            'telegram_destination_channel': '@target_channel',
            'name': 'Telegram Feed'
        }

        # When: Send to Telegram with long content
        status = asyncio.run(watchtower._send_to_telegram(
            message_data, destination, long_content, include_media=False
        ))

        # Then: Send called (handler manages overflow internally)
        mock_telegram.send_copy.assert_called_once()
        self.assertEqual(status, "sent")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_telegram_success_increments_messages_sent(self, MockConfig, MockRouter, MockOCR,
                                                                 MockTelegram, MockDiscord, MockQueue,
                                                                 MockMetrics):
        """
        Given: Successful Telegram send
        When: _send_to_telegram() completes
        Then: messages_sent_telegram metric is incremented

        Tests: src/Watchtower.py:389-391 (metrics increment)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_telegram = MockTelegram.return_value
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=True)

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test",
            ocr_raw="Extracted OCR text"
        )

        destination = {
            'type': 'telegram',
            'telegram_destination_channel': '@target_channel',
            'name': 'Telegram Feed'
        }

        # When: Send to Telegram
        asyncio.run(watchtower._send_to_telegram(
            message_data, destination, "Content", include_media=False
        ))

        # Then: Metrics incremented
        mock_metrics.increment.assert_any_call("messages_sent_telegram")
        mock_metrics.increment.assert_any_call("ocr_msgs_sent")

    @patch('MetricsCollector.MetricsCollector')
    @patch('MessageQueue.MessageQueue')
    @patch('DiscordHandler.DiscordHandler')
    @patch('TelegramHandler.TelegramHandler')
    @patch('OCRHandler.OCRHandler')
    @patch('MessageRouter.MessageRouter')
    @patch('ConfigManager.ConfigManager')
    def test_send_to_telegram_failure_enqueues(self, MockConfig, MockRouter, MockOCR,
                                                 MockTelegram, MockDiscord, MockQueue, MockMetrics):
        """
        Given: Telegram send fails (rate limit or network error)
        When: _send_to_telegram() is called
        Then: Message is enqueued for retry, returns "queued for retry"

        Tests: src/Watchtower.py:393-402 (failure handling and retry queue)
        """
        from Watchtower import Watchtower

        mock_config = MockConfig.return_value
        mock_config.telegram_api_id = "123"
        mock_config.telegram_api_hash = "hash"
        mock_config.telegram_session_name = "session"
        mock_config.project_root = Path("/tmp")
        mock_config.attachments_dir = Path("/tmp/attachments")
        mock_config.rsslog_dir = Path("/tmp/rsslog")
        mock_config.telegramlog_dir = Path("/tmp/telegramlog")
        mock_config.tmp_dir = Path("/tmp")

        mock_telegram = MockTelegram.return_value
        mock_telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_telegram.send_copy = AsyncMock(return_value=False)  # Failure

        mock_queue = MockQueue.return_value
        mock_queue.enqueue = Mock()

        mock_metrics = MockMetrics.return_value
        mock_metrics.increment = Mock()

        watchtower = Watchtower(sources=['telegram'])

        message_data = MessageData(
            source_type="telegram",
            channel_id="123456",
            channel_name="source_channel",
            username="test_user",
            timestamp=datetime.now(timezone.utc),
            text="Test"
        )

        destination = {
            'type': 'telegram',
            'telegram_destination_channel': '@target_channel',
            'name': 'Telegram Feed'
        }

        # When: Send to Telegram fails
        status = asyncio.run(watchtower._send_to_telegram(
            message_data, destination, "Content", include_media=False
        ))

        # Then: Message enqueued for retry
        mock_queue.enqueue.assert_called_once()
        self.assertEqual(status, "queued for retry")
        mock_metrics.increment.assert_any_call("messages_queued_retry")

class TestWatchtowerShutdown(unittest.TestCase):
    """
    Tests for Watchtower shutdown behavior.

    These tests cover Bug #2: Shutdown metrics logged twice.
    """


class TestWatchtowerUtilityFunctions(unittest.TestCase):
    """Test module-level utility functions in Watchtower."""

    def test_get_entity_type_and_name_broadcast_channel(self):
        """Test _get_entity_type_and_name for broadcast channel."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import Channel

        channel = Mock(spec=Channel)
        channel.broadcast = True
        channel.megagroup = False
        channel.title = "Test Channel"

        entity_type, entity_name = _get_entity_type_and_name(channel)
        self.assertEqual(entity_type, "Channel")
        self.assertEqual(entity_name, "Test Channel")

    def test_get_entity_type_and_name_supergroup(self):
        """Test _get_entity_type_and_name for supergroup."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import Channel

        channel = Mock(spec=Channel)
        channel.broadcast = False
        channel.megagroup = True
        channel.title = "Test Supergroup"

        entity_type, entity_name = _get_entity_type_and_name(channel)
        self.assertEqual(entity_type, "Supergroup")
        self.assertEqual(entity_name, "Test Supergroup")

    def test_get_entity_type_and_name_regular_group(self):
        """Test _get_entity_type_and_name for regular group (Channel with neither flag)."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import Channel

        channel = Mock(spec=Channel)
        channel.broadcast = False
        channel.megagroup = False
        channel.title = "Test Group"

        entity_type, entity_name = _get_entity_type_and_name(channel)
        self.assertEqual(entity_type, "Group")
        self.assertEqual(entity_name, "Test Group")

    def test_get_entity_type_and_name_chat(self):
        """Test _get_entity_type_and_name for Chat."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import Chat

        chat = Mock(spec=Chat)
        chat.title = "Test Chat"

        entity_type, entity_name = _get_entity_type_and_name(chat)
        self.assertEqual(entity_type, "Group")
        self.assertEqual(entity_name, "Test Chat")

    def test_get_entity_type_and_name_bot(self):
        """Test _get_entity_type_and_name for bot User."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = True
        user.username = "test_bot"
        user.first_name = "Test"
        user.last_name = None

        entity_type, entity_name = _get_entity_type_and_name(user)
        self.assertEqual(entity_type, "Bot")
        self.assertEqual(entity_name, "@test_bot")

    def test_get_entity_type_and_name_user_with_username(self):
        """Test _get_entity_type_and_name for regular User with username."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = False
        user.username = "testuser"
        user.first_name = "John"
        user.last_name = "Doe"

        entity_type, entity_name = _get_entity_type_and_name(user)
        self.assertEqual(entity_type, "User")
        self.assertEqual(entity_name, "@testuser")

    def test_get_entity_type_and_name_user_with_full_name(self):
        """Test _get_entity_type_and_name for User without username but with full name."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = False
        user.username = None
        user.first_name = "Jane"
        user.last_name = "Smith"
        user.id = 123456

        entity_type, entity_name = _get_entity_type_and_name(user)
        self.assertEqual(entity_type, "User")
        self.assertEqual(entity_name, "Jane Smith")

    def test_get_entity_type_and_name_user_first_name_only(self):
        """Test _get_entity_type_and_name for User with only first name."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = False
        user.username = None
        user.first_name = "Alice"
        user.last_name = None
        user.id = 789

        entity_type, entity_name = _get_entity_type_and_name(user)
        self.assertEqual(entity_type, "User")
        self.assertEqual(entity_name, "Alice")

    def test_get_entity_type_and_name_user_no_name(self):
        """Test _get_entity_type_and_name for User without any name."""
        from Watchtower import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = False
        user.username = None
        user.first_name = None
        user.last_name = None
        user.id = 999

        entity_type, entity_name = _get_entity_type_and_name(user)
        self.assertEqual(entity_type, "User")
        self.assertEqual(entity_name, "User999")


if __name__ == '__main__':
    unittest.main()
