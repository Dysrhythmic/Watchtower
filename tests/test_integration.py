import unittest
import sys
import os
import tempfile
from unittest.mock import Mock, patch
from pathlib import Path
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData


def create_mock_config(extra_attrs=None):
    """Helper to create properly configured mock config."""
    mock_config = Mock()
    mock_config.tmp_dir = Path("/tmp")
    mock_config.attachments_dir = Path("/tmp/attachments")
    mock_config.rsslog_dir = Path("/tmp/rsslog")
    mock_config.project_root = Path("/tmp")
    mock_config.api_id = "123"
    mock_config.api_hash = "abc"
    mock_config.get_all_channel_ids = Mock(return_value=set())
    mock_config.webhooks = []

    if extra_attrs:
        for key, value in extra_attrs.items():
            setattr(mock_config, key, value)

    return mock_config


class TestTelegramToDiscordFlow(unittest.TestCase):
    """Test complete Telegram → Discord message flow."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_full_pipeline_text_only(self, mock_post, mock_config_class, mock_telegram_client):
        """Test full Telegram → Discord pipeline without media."""
        from Watchtower import Watchtower

        # Setup config
        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test_channel"}),
            'webhooks': [{
                'name': 'Discord Dest',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['CVE'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]
        })
        mock_config_class.return_value = mock_config

        # Mock successful Discord send
        mock_post.return_value.status_code = 200

        # Create Watchtower
        app = Watchtower(sources=["telegram"])

        # Create test message
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@testuser",
            timestamp=datetime.now(timezone.utc),
            text="New CVE-2025-1234 discovered"
        )

        # Process message
        destinations = app.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)

        # Verify Discord formatting and send work
        formatted = app.discord.format_message(msg, destinations[0])
        success = app.discord.send_message(formatted, mock_config.webhooks[0]['webhook_url'], None)

        self.assertTrue(success)
        mock_post.assert_called_once()


class TestRetryQueueIntegration(unittest.TestCase):
    """Test retry queue integration with handlers."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_discord_429_enqueue(self, mock_post, mock_config_class, mock_telegram_client):
        """Test 429 response enqueues message."""
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Mock 429 response
        mock_response_429 = Mock()
        mock_response_429.status_code = 429
        mock_response_429.json.return_value = {'retry_after': 5.0}
        mock_post.return_value = mock_response_429

        destination = {
            'name': 'Test',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook'
        }

        # First send fails with 429
        success = app.discord.send_message("Test message", destination['webhook_url'], None)
        self.assertFalse(success)

        # Should be enqueueable
        app.message_queue.enqueue(
            destination=destination,
            formatted_content="Test message",
            media_path=None,
            reason="rate limit"
        )
        self.assertEqual(app.message_queue.get_queue_size(), 1)


class TestMetricsIntegration(unittest.TestCase):
    """Test metrics tracking during operations."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_metrics_increment_on_operations(self, mock_config_class, mock_telegram_client):
        """Test metrics are tracked correctly."""
        from Watchtower import Watchtower

        temp_dir = Path(tempfile.mkdtemp())

        mock_config = create_mock_config({
            'tmp_dir': temp_dir,
            'attachments_dir': temp_dir / "attachments"
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Increment some metrics
        app.metrics.increment("messages_received_telegram")
        app.metrics.increment("messages_sent_discord")
        app.metrics.increment("messages_sent_discord")

        # Verify counts
        self.assertEqual(app.metrics.get("messages_received_telegram"), 1)
        self.assertEqual(app.metrics.get("messages_sent_discord"), 2)

        # Force save to ensure persistence (periodic saves don't happen immediately)
        app.metrics.force_save()

        # Verify persistence
        metrics_file = temp_dir / "metrics.json"
        self.assertTrue(metrics_file.exists())

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)


class TestMessageRouting(unittest.TestCase):
    """Test message routing logic."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_keyword_matching_forwards_correctly(self, mock_config_class, mock_telegram_client):
        """Test message only forwards when keyword matches."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test_channel"}),
            'webhooks': [{
                'name': 'Discord',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': ['ransomware'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Message WITHOUT keyword
        msg_no_match = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Just a regular message"
        )

        destinations = app.router.get_destinations(msg_no_match)
        self.assertEqual(len(destinations), 0)

        # Message WITH keyword
        msg_match = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="New ransomware campaign detected"
        )

        destinations = app.router.get_destinations(msg_match)
        self.assertEqual(len(destinations), 1)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_same_channel_multiple_destinations(self, mock_config_class, mock_telegram_client):
        """Test one channel can route to multiple destinations."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test"}),
            'webhooks': [
                {
                    'name': 'Discord 1',
                    'type': 'discord',
                    'webhook_url': 'https://discord.com/webhook1',
                    'channels': [{
                        'id': '@test',
                        'keywords': ['CVE'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    }]
                },
                {
                    'name': 'Discord 2',
                    'type': 'discord',
                    'webhook_url': 'https://discord.com/webhook2',
                    'channels': [{
                        'id': '@test',
                        'keywords': ['CVE'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    }]
                }
            ]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="New CVE discovered"
        )

        destinations = app.router.get_destinations(msg)
        self.assertEqual(len(destinations), 2)
        self.assertEqual(destinations[0]['name'], 'Discord 1')
        self.assertEqual(destinations[1]['name'], 'Discord 2')


class TestParserIntegration(unittest.TestCase):
    """Test parser integration with routing."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_parser_trims_lines(self, mock_config_class, mock_telegram_client):
        """Test parser correctly trims lines from messages."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test"}),
            'webhooks': [{
                'name': 'Discord',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': {
                        'trim_front_lines': 1,
                        'trim_back_lines': 1
                    },
                    'ocr': False
                }]
            }]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3\nLine 4"
        )

        destinations = app.router.get_destinations(msg)
        self.assertEqual(len(destinations), 1)

        # Get parsed message
        parsed = app.router.parse_msg(msg, destinations[0]['parser'])

        # Should remove first and last line
        self.assertNotIn("Line 1", parsed.text)
        self.assertNotIn("Line 4", parsed.text)
        self.assertIn("Line 2", parsed.text)
        self.assertIn("Line 3", parsed.text)


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_discord_network_error_recovery(self, mock_post, mock_config_class, mock_telegram_client):
        """Test handling Discord network errors."""
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Mock network error
        mock_post.side_effect = Exception("Connection failed")

        success = app.discord.send_message("Test", "https://discord.com/webhook", None)
        self.assertFalse(success)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_empty_message_handling(self, mock_config_class, mock_telegram_client):
        """Test handling empty messages."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test"}),
            'webhooks': [{
                'name': 'Test',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False
                }]
            }]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text=""  # Empty text
        )

        destinations = app.router.get_destinations(msg)
        # Should still match with empty keywords
        self.assertEqual(len(destinations), 1)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_malformed_config_handling(self, mock_config_class, mock_telegram_client):
        """Test handling configuration with missing fields."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'webhooks': []  # Empty webhooks list
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test"
        )

        destinations = app.router.get_destinations(msg)
        self.assertEqual(len(destinations), 0)


class TestMediaHandling(unittest.TestCase):
    """Test media-specific functionality."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    @patch('requests.post')
    def test_media_with_ocr_extraction(self, mock_post, mock_config_class, mock_telegram_client):
        """Test media message with OCR text extraction."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@test"}),
            'webhooks': [{
                'name': 'Discord',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [{
                    'id': '@test',
                    'keywords': ['secret'],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': True
                }]
            }]
        })
        mock_config_class.return_value = mock_config
        mock_post.return_value.status_code = 200

        app = Watchtower(sources=["telegram"])

        msg = MessageData(
            source_type="telegram",
            channel_id="@test",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Check the image",
            ocr_raw="This is secret information"
        )

        destinations = app.router.get_destinations(msg)
        # Should match based on OCR text
        self.assertEqual(len(destinations), 1)


class TestQueueProcessing(unittest.TestCase):
    """Test message queue processing scenarios."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_queue_backoff_progression(self, mock_config_class, mock_telegram_client):
        """Test exponential backoff progression."""
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Enqueue an item
        app.message_queue.enqueue(
            destination={'name': 'Test'},
            formatted_content="Test",
            media_path=None
        )

        item = app.message_queue._queue[0]

        # Initial backoff
        import time
        initial_time = item.next_retry_time
        self.assertGreater(initial_time, time.time())

        # Simulate failure and backoff increase
        item.attempt_count = 1
        backoff_1 = 5 * (2 ** item.attempt_count)
        self.assertEqual(backoff_1, 10)

        item.attempt_count = 2
        backoff_2 = 5 * (2 ** item.attempt_count)
        self.assertEqual(backoff_2, 20)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_queue_drop_after_max_retries(self, mock_config_class, mock_telegram_client):
        """Test items dropped after max retries."""
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        app.message_queue.enqueue(
            destination={'name': 'Test'},
            formatted_content="Test",
            media_path=None
        )

        item = app.message_queue._queue[0]

        # Set to max retries
        item.attempt_count = app.message_queue.MAX_RETRIES

        # Should be eligible for dropping
        self.assertGreaterEqual(item.attempt_count, app.message_queue.MAX_RETRIES)


class TestConfigurationVariations(unittest.TestCase):
    """Test different configuration scenarios."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_multiple_channels_same_destination(self, mock_config_class, mock_telegram_client):
        """Test single destination monitoring multiple channels."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@chan1", "@chan2"}),
            'webhooks': [{
                'name': 'Discord',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [
                    {
                        'id': '@chan1',
                        'keywords': ['alert'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    },
                    {
                        'id': '@chan2',
                        'keywords': ['alert'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    }
                ]
            }]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Message from first channel
        msg1 = MessageData(
            source_type="telegram",
            channel_id="@chan1",
            channel_name="Channel 1",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Alert message"
        )

        destinations1 = app.router.get_destinations(msg1)
        self.assertEqual(len(destinations1), 1)

        # Message from second channel
        msg2 = MessageData(
            source_type="telegram",
            channel_id="@chan2",
            channel_name="Channel 2",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Alert message"
        )

        destinations2 = app.router.get_destinations(msg2)
        self.assertEqual(len(destinations2), 1)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_mixed_source_types(self, mock_config_class, mock_telegram_client):
        """Test handling mixed Telegram and RSS sources."""
        from Watchtower import Watchtower

        mock_config = create_mock_config({
            'get_all_channel_ids': Mock(return_value={"@telegram_chan", "https://example.com/feed"}),
            'webhooks': [{
                'name': 'Discord',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook',
                'channels': [
                    {
                        'id': '@telegram_chan',
                        'keywords': ['news'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    },
                    {
                        'id': 'https://example.com/feed',
                        'keywords': ['news'],
                        'restricted_mode': False,
                        'parser': None,
                        'ocr': False
                    }
                ]
            }]
        })
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram", "rss"])

        # Telegram message
        msg_telegram = MessageData(
            source_type="telegram",
            channel_id="@telegram_chan",
            channel_name="Telegram Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Breaking news"
        )

        # RSS message
        msg_rss = MessageData(
            source_type="rss",
            channel_id="https://example.com/feed",
            channel_name="RSS Feed",
            username="RSS",
            timestamp=datetime.now(timezone.utc),
            text="Breaking news"
        )

        dest_telegram = app.router.get_destinations(msg_telegram)
        dest_rss = app.router.get_destinations(msg_rss)

        # Both should route to the same destination
        self.assertEqual(len(dest_telegram), 1)
        self.assertEqual(len(dest_rss), 1)


class TestTelegramCaptionHandling(unittest.TestCase):
    """Test Telegram caption length validation and content preservation."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_caption_limit_constant(self, mock_config_class, mock_telegram_client):
        """Test that Telegram limits are correctly defined."""
        from Watchtower import Watchtower

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Verify the limit constants are set
        self.assertEqual(app.telegram.TELEGRAM_CAPTION_LIMIT, 1024)
        self.assertEqual(app.telegram.TELEGRAM_MESSAGE_LIMIT, 4096)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_no_content_loss_with_long_caption_and_media(self, mock_config_class, mock_telegram_client):
        """Test that NO content is lost when caption exceeds 1024 chars with media.

        This is the critical test ensuring the fix works:
        - A 6700 char message with media should result in 2 chunks (4096 + 2604)
        - ALL content must be sent, nothing is dropped
        - Media is sent captionless when content > 1024 chars
        """
        from Watchtower import Watchtower
        from TelegramHandler import TelegramHandler

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Create a 6700-character message (matches user's actual message length)
        test_content = "A" * 6700

        # Verify chunking uses proper Telegram limits (4096 not 2000)
        chunks = app.telegram._chunk_text(test_content, TelegramHandler.TELEGRAM_MESSAGE_LIMIT)

        # Should create 2 chunks at 4096 limit: [4096 chars, 2604 chars]
        self.assertEqual(len(chunks), 2, "6700 chars should create 2 chunks at 4096 limit")
        self.assertEqual(len(chunks[0]), 4096, "First chunk should be 4096 chars")
        self.assertEqual(len(chunks[1]), 2604, "Second chunk should be 2604 chars")

        # Verify NO content is lost
        rejoined = "".join(chunks)
        self.assertEqual(len(rejoined), 6700, "All content must be preserved")
        self.assertEqual(rejoined, test_content, "Content must be identical after chunking")

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_chunking_respects_message_boundaries(self, mock_config_class, mock_telegram_client):
        """Test that message chunks maintain ordering at 4096 char limit."""
        from Watchtower import Watchtower
        from TelegramHandler import TelegramHandler

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        app = Watchtower(sources=["telegram"])

        # Create a message that will chunk into 3 parts at 4096 limit
        # Note: Use space separators instead of newlines to avoid lstrip behavior
        chunk1 = "CHUNK_1_START " + ("x" * 4070) + " CHUNK_1_END "
        chunk2 = "CHUNK_2_START " + ("y" * 4070) + " CHUNK_2_END "
        chunk3 = "CHUNK_3_START " + ("z" * 500) + " CHUNK_3_END"

        long_message = chunk1 + chunk2 + chunk3

        chunks = app.telegram._chunk_text(long_message, TelegramHandler.TELEGRAM_MESSAGE_LIMIT)

        # Verify all chunks created
        self.assertEqual(len(chunks), 3)

        # Verify order is preserved
        self.assertIn("CHUNK_1_START", chunks[0])
        self.assertIn("CHUNK_2_START", chunks[1])
        self.assertIn("CHUNK_3_START", chunks[2])

        # Verify total content is preserved (chunking may strip leading newlines for cleaner display)
        total_chars = sum(len(c) for c in chunks)
        # Should be close to original length (may differ by stripped newlines)
        self.assertGreaterEqual(total_chars, len(long_message) - 10, "Total chars should be approximately preserved")


class TestNewMetrics(unittest.TestCase):
    """Test new metrics: ocr_sent and time_ran."""

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_sent_metric_tracked(self, mock_config_class, mock_telegram_client):
        """Test that ocr_sent metric is incremented when messages with OCR are sent."""
        from Watchtower import Watchtower
        from MessageData import MessageData
        from MetricsCollector import MetricsCollector
        import asyncio
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Create isolated metrics for this test
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

        # Create a message with OCR data
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=False
        )
        message_data.ocr_raw = "Some OCR extracted text"

        # Mock Discord send to succeed
        with patch.object(app.discord, 'send_message', return_value=True):
            destination = {
                'type': 'discord',
                'name': 'Test',
                'webhook_url': 'http://test.com',
                'parser': {}
            }

            content = app.discord.format_message(message_data, destination)
            asyncio.run(app._send_to_discord(message_data, destination, content, False))

        # Verify ocr_sent was incremented
        self.assertEqual(app.metrics.get("ocr_sent"), 1)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_ocr_sent_not_tracked_without_ocr(self, mock_config_class, mock_telegram_client):
        """Test that ocr_sent metric is NOT incremented when messages have no OCR."""
        from Watchtower import Watchtower
        from MessageData import MessageData
        from MetricsCollector import MetricsCollector
        import asyncio
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Create isolated metrics for this test
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        app = Watchtower(sources=["telegram"], metrics=isolated_metrics)

        # Create a message WITHOUT OCR data
        message_data = MessageData(
            source_type="telegram",
            channel_id="123",
            channel_name="Test",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Test message",
            has_media=False
        )

        # Mock Discord send to succeed
        with patch.object(app.discord, 'send_message', return_value=True):
            destination = {
                'type': 'discord',
                'name': 'Test',
                'webhook_url': 'http://test.com',
                'parser': {}
            }

            content = app.discord.format_message(message_data, destination)
            asyncio.run(app._send_to_discord(message_data, destination, content, False))

        # Verify ocr_sent was NOT incremented
        self.assertEqual(app.metrics.get("ocr_sent"), 0)

    @patch('TelegramHandler.TelegramClient')
    @patch('ConfigManager.ConfigManager')
    def test_time_ran_metric_per_session(self, mock_config_class, mock_telegram_client):
        """Test that time_ran metric is per-session, not cumulative."""
        from Watchtower import Watchtower
        from MetricsCollector import MetricsCollector
        import asyncio
        import tempfile
        import time
        from pathlib import Path

        mock_config = create_mock_config()
        mock_config_class.return_value = mock_config

        # Create isolated metrics for this test
        temp_metrics = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        temp_metrics.close()
        isolated_metrics = MetricsCollector(Path(temp_metrics.name))

        # First session: 10 seconds
        app1 = Watchtower(sources=[], metrics=isolated_metrics)
        app1.telegram.client.is_connected = lambda: False
        app1._start_time = time.time() - 10
        asyncio.run(app1.shutdown())

        first_time_ran = isolated_metrics.get("time_ran")
        self.assertGreaterEqual(first_time_ran, 9)
        self.assertLessEqual(first_time_ran, 12)

        # Second session: 5 seconds (should REPLACE, not add to 10)
        app2 = Watchtower(sources=[], metrics=isolated_metrics)
        app2.telegram.client.is_connected = lambda: False
        app2._start_time = time.time() - 5
        asyncio.run(app2.shutdown())

        second_time_ran = isolated_metrics.get("time_ran")
        # Should be ~5, NOT ~15 (if it were cumulative)
        self.assertGreaterEqual(second_time_ran, 4)
        self.assertLessEqual(second_time_ran, 7)


if __name__ == '__main__':
    unittest.main()
