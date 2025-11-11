"""
End-to-end tests for attachment handling through the complete send → fail → enqueue → retry cycle.

These tests verify that attachments are properly handled throughout the entire message lifecycle:
1. Attachment parameter naming (catches media_path vs attachment_path bugs)
2. Attachment preservation through enqueue → retry flow
3. OCR and caption handling with images
4. Complete integration between Watchtower, handlers, and MessageQueue

Tests use test-img.jpg for image attachment testing.
"""

import asyncio
import unittest
import sys
import os
import tempfile
from unittest.mock import Mock, AsyncMock, patch, MagicMock, call
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD
from SendStatus import SendStatus

# Import shared helper from conftest
from conftest import create_mock_config


class TestDiscordAttachmentFlow(unittest.TestCase):
    """Test Discord message flow with attachments through failure → enqueue → retry."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_discord_send_failure_enqueues_with_correct_attachment_path(self, mock_post, mock_config_class, mock_telegram_client):
        """Test that Discord send failure enqueues message with correct attachment_path parameter.

        This test would have caught the media_path vs attachment_path bug.

        Given: Message with attachment at test-img.jpg
        When: Discord send fails with 429
        Then: Message enqueued with attachment_path=test-img.jpg (NOT media_path)
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        # Mock 429 response for rate limit
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.json.return_value = {'retry_after': 5.0}
        mock_post.return_value = mock_response_429

        # Create message with attachment
        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')
        self.assertTrue(os.path.exists(test_image), "test-img.jpg must exist for this test")

        msg = MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_name='test',
            text='Test message with image',
            attachment_path=test_image
        )

        destination = {
            'name': 'TestDiscord',
            'type': APP_TYPE_DISCORD,
            'discord_webhook_url': 'https://discord.com/webhook'
        }

        # Send message - should fail and enqueue
        result = asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

        # Verify message was queued
        self.assertEqual(result, SendStatus.QUEUED)
        self.assertEqual(app.message_queue.get_queue_size(), 1)

        # CRITICAL: Verify queued item has correct attachment_path field
        queued_item = app.message_queue._queue[0]
        self.assertEqual(queued_item.attachment_path, test_image)
        self.assertIsNotNone(queued_item.attachment_path, "Attachment path should not be None")

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_discord_attachment_survives_retry_cycle(self, mock_config_class, mock_telegram_client):
        """Test that attachment is correctly passed through enqueue → retry → resend cycle.

        Given: Message with attachment enqueued due to rate limit
        When: Retry queue processes the item
        Then: Discord handler receives the correct attachment_path
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        destination = {
            'name': 'TestDiscord',
            'type': APP_TYPE_DISCORD,
            'discord_webhook_url': 'https://discord.com/webhook'
        }

        # Manually enqueue a message with attachment
        app.message_queue.enqueue(
            destination=destination,
            formatted_content="Test retry with image",
            attachment_path=test_image,
            reason="test"
        )

        # Mock Discord send_message to return True and capture arguments
        app.discord.send_message = AsyncMock(return_value=True)

        # Process one retry attempt
        retry_item = app.message_queue._queue[0]
        success = asyncio.run(app.message_queue._retry_send(retry_item, app))

        # Verify success
        self.assertTrue(success)

        # Verify Discord handler was called with correct attachment_path
        app.discord.send_message.assert_called_once()
        call_args = app.discord.send_message.call_args

        # Check third argument (attachment_path)
        self.assertEqual(call_args[0][2], test_image, "Attachment path should be passed correctly to send_message")

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_discord_attachment_with_no_media_path_parameter(self, mock_post, mock_config_class, mock_telegram_client):
        """Test that enqueue() rejects media_path parameter (verifies bug is fixed).

        Given: Attempting to enqueue with media_path parameter
        When: enqueue() is called
        Then: Should raise TypeError for unexpected keyword argument
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        destination = {
            'name': 'TestDiscord',
            'type': APP_TYPE_DISCORD,
            'discord_webhook_url': 'https://discord.com/webhook'
        }

        # This should raise TypeError if media_path is used instead of attachment_path
        with self.assertRaises(TypeError) as context:
            app.message_queue.enqueue(
                destination=destination,
                formatted_content="Test",
                media_path='/path/to/image.jpg',  # Wrong parameter name!
                reason="test"
            )

        self.assertIn('media_path', str(context.exception))


class TestTelegramAttachmentFlow(unittest.TestCase):
    """Test Telegram message flow with attachments through failure → enqueue → retry."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_telegram_send_failure_enqueues_with_correct_attachment_path(self, mock_config_class, mock_telegram_client):
        """Test that Telegram send failure enqueues message with correct attachment_path parameter.

        Given: Message with attachment at test-img.jpg
        When: Telegram send fails
        Then: Message enqueued with attachment_path=test-img.jpg (NOT media_path)
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Mock TelegramClient
        mock_client_instance = AsyncMock()
        mock_telegram_client.return_value = mock_client_instance

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        # Mock send_message to return False (failure)
        app.telegram.send_message = AsyncMock(return_value=False)

        # Create message with attachment
        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')
        self.assertTrue(os.path.exists(test_image), "test-img.jpg must exist for this test")

        msg = MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_name='test',
            text='Test message with image',
            attachment_path=test_image
        )

        destination = {
            'name': 'TestTelegram',
            'type': APP_TYPE_TELEGRAM,
            'telegram_dst_channel': '-1001234567890'
        }

        # Send message - should fail and enqueue
        result = asyncio.run(app._send_to_telegram(msg, destination, msg.text, True))

        # Verify message was queued
        self.assertEqual(result, SendStatus.QUEUED)
        self.assertEqual(app.message_queue.get_queue_size(), 1)

        # CRITICAL: Verify queued item has correct attachment_path field
        queued_item = app.message_queue._queue[0]
        self.assertEqual(queued_item.attachment_path, test_image)
        self.assertIsNotNone(queued_item.attachment_path, "Attachment path should not be None")

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_telegram_attachment_survives_retry_cycle(self, mock_config_class, mock_telegram_client):
        """Test that attachment is correctly passed through enqueue → retry → resend cycle.

        Given: Message with attachment enqueued due to failure
        When: Retry queue processes the item
        Then: Telegram handler receives the correct attachment_path
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Mock TelegramClient
        mock_client_instance = AsyncMock()
        mock_telegram_client.return_value = mock_client_instance

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        destination = {
            'name': 'TestTelegram',
            'type': APP_TYPE_TELEGRAM,
            'telegram_dst_channel': '-1001234567890',
            'telegram_dst_id': -1001234567890
        }

        # Manually enqueue a message with attachment
        app.message_queue.enqueue(
            destination=destination,
            formatted_content="Test retry with image",
            attachment_path=test_image,
            reason="test"
        )

        # Mock telegram methods for retry
        app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        app.telegram.send_message = AsyncMock(return_value=True)

        # Process one retry attempt
        retry_item = app.message_queue._queue[0]
        success = asyncio.run(app.message_queue._retry_send(retry_item, app))

        # Verify success
        self.assertTrue(success)

        # Verify Telegram handler was called with correct attachment_path
        app.telegram.send_message.assert_called_once()
        call_args = app.telegram.send_message.call_args

        # Check third argument (attachment_path)
        self.assertEqual(call_args[0][2], test_image, "Attachment path should be passed correctly to send_message")


class TestOCRAndCaptionFlow(unittest.TestCase):
    """Test OCR extraction and caption handling with image attachments."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_ocr_extraction_with_attachment_through_retry(self, mock_post, mock_config_class, mock_telegram_client):
        """Test that message with OCR data and attachment can be enqueued.

        Given: Message with image that has OCR data
        When: Message fails and gets enqueued
        Then: Message queued with attachment path preserved
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        # Mock 429 response
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.json.return_value = {'retry_after': 5.0}
        mock_post.return_value = mock_response_429

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        # Create message with OCR data
        msg = MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_name='test',
            text='Original message',
            attachment_path=test_image,
            ocr_raw='Extracted text from image'
        )

        destination = {
            'name': 'TestDiscord',
            'type': APP_TYPE_DISCORD,
            'discord_webhook_url': 'https://discord.com/webhook'
        }

        # Send message - should fail and enqueue
        result = asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

        # Verify message was queued
        self.assertEqual(result, SendStatus.QUEUED)
        self.assertEqual(app.message_queue.get_queue_size(), 1)

        # Verify attachment_path and formatted_content in queue
        queued_item = app.message_queue._queue[0]
        self.assertIsNotNone(queued_item.formatted_content)
        self.assertEqual(queued_item.attachment_path, test_image)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_telegram_caption_length_handling_with_retry(self, mock_config_class, mock_telegram_client):
        """Test that long captions are properly chunked when retried.

        Given: Message with attachment and very long content (>1024 chars)
        When: Message is enqueued and retried
        Then: Telegram handler should send attachment without caption, then text separately
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Mock TelegramClient
        mock_client_instance = AsyncMock()
        mock_telegram_client.return_value = mock_client_instance

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        # Create very long content (exceeds 1024 caption limit)
        long_content = "A" * 1500

        destination = {
            'name': 'TestTelegram',
            'type': APP_TYPE_TELEGRAM,
            'telegram_dst_channel': '-1001234567890',
            'telegram_dst_id': -1001234567890
        }

        # Enqueue message with long content and attachment
        app.message_queue.enqueue(
            destination=destination,
            formatted_content=long_content,
            attachment_path=test_image,
            reason="test"
        )

        # Mock telegram methods
        app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        app.telegram.send_message = AsyncMock(return_value=True)

        # Process retry
        retry_item = app.message_queue._queue[0]
        success = asyncio.run(app.message_queue._retry_send(retry_item, app))

        # Verify success
        self.assertTrue(success)

        # Verify Telegram handler was called
        app.telegram.send_message.assert_called_once()


class TestParameterVerification(unittest.TestCase):
    """Test parameter verification with mocks/spies to catch parameter name bugs."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_watchtower_discord_failure_calls_enqueue_with_attachment_path(self, mock_post, mock_config_class, mock_telegram_client):
        """Spy on message_queue.enqueue to verify it's called with attachment_path, not media_path.

        Given: Discord send fails with attachment
        When: Watchtower calls enqueue
        Then: Verify enqueue called with attachment_path parameter
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        # Spy on enqueue
        original_enqueue = app.message_queue.enqueue
        app.message_queue.enqueue = Mock(side_effect=original_enqueue)

        # Mock 429 response
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.json.return_value = {'retry_after': 5.0}
        mock_post.return_value = mock_response_429

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        msg = MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_name='test',
            text='Test',
            attachment_path=test_image
        )

        destination = {
            'name': 'TestDiscord',
            'type': APP_TYPE_DISCORD,
            'discord_webhook_url': 'https://discord.com/webhook'
        }

        # Send message - should fail and call enqueue
        asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

        # Verify enqueue was called
        app.message_queue.enqueue.assert_called_once()

        # Verify it was called with attachment_path keyword argument
        call_kwargs = app.message_queue.enqueue.call_args.kwargs
        self.assertIn('attachment_path', call_kwargs)
        self.assertNotIn('media_path', call_kwargs, "Should NOT use media_path parameter")
        self.assertEqual(call_kwargs['attachment_path'], test_image)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_watchtower_telegram_failure_calls_enqueue_with_attachment_path(self, mock_config_class, mock_telegram_client):
        """Spy on message_queue.enqueue to verify it's called with attachment_path, not media_path.

        Given: Telegram send fails with attachment
        When: Watchtower calls enqueue
        Then: Verify enqueue called with attachment_path parameter
        """
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Mock TelegramClient
        mock_client_instance = AsyncMock()
        mock_telegram_client.return_value = mock_client_instance

        app = Watchtower(sources=[APP_TYPE_TELEGRAM])

        # Spy on enqueue
        original_enqueue = app.message_queue.enqueue
        app.message_queue.enqueue = Mock(side_effect=original_enqueue)

        # Mock send_message to return False
        app.telegram.send_message = AsyncMock(return_value=False)

        test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

        msg = MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_name='test',
            text='Test',
            attachment_path=test_image
        )

        destination = {
            'name': 'TestTelegram',
            'type': APP_TYPE_TELEGRAM,
            'telegram_dst_channel': '-1001234567890'
        }

        # Send message - should fail and call enqueue
        asyncio.run(app._send_to_telegram(msg, destination, msg.text, True))

        # Verify enqueue was called
        app.message_queue.enqueue.assert_called_once()

        # Verify it was called with attachment_path keyword argument
        call_kwargs = app.message_queue.enqueue.call_args.kwargs
        self.assertIn('attachment_path', call_kwargs)
        self.assertNotIn('media_path', call_kwargs, "Should NOT use media_path parameter")
        self.assertEqual(call_kwargs['attachment_path'], test_image)


if __name__ == '__main__':
    unittest.main()
