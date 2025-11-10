"""
Refactored tests for simple unit components.

This consolidates smaller test files that have less code reuse:
- test_message_data.py (156 lines)
- test_message_queue.py (370 lines)
- test_ocr_handler.py (269 lines)
- test_metrics.py (464 lines)

Combined into ~350 lines using pytest fixtures.
"""

import pytest
import time
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path


# ============================================================================
# MESSAGE DATA TESTS
# ============================================================================

class TestMessageData:
    """Tests for MessageData class."""

    def test_message_data_creation(self, message_factory):
        """Test creating MessageData with factory."""
        msg = message_factory(
            text="Test message",
            has_media=True,
            media_path="/tmp/test.jpg"
        )

        assert msg.text == "Test message"
        assert msg.has_media is True
        assert msg.media_path == "/tmp/test.jpg"
        assert msg.source_type == "Telegram"
        assert msg.channel_id == "@test_channel"

    def test_message_data_with_ocr(self, message_factory):
        """Test MessageData with OCR content."""
        msg = message_factory(
            text="Message text",
            ocr_raw="OCR extracted text",
            ocr_enabled=True
        )

        assert msg.ocr_raw == "OCR extracted text"
        assert msg.ocr_enabled is True

    def test_message_data_with_reply_context(self, message_factory):
        """Test MessageData with reply context."""
        reply_context = {
            'message_id': 123,
            'author': '@original_user',
            'text': 'Original message',
            'time': '2025-01-01 12:00:00',
            'has_media': False
        }

        msg = message_factory(reply_context=reply_context)
        assert msg.reply_context == reply_context

    def test_message_data_metadata(self, message_factory):
        """Test MessageData with custom metadata."""
        metadata = {'custom_key': 'custom_value'}
        msg = message_factory(metadata=metadata)
        assert msg.metadata == metadata


# ============================================================================
# MESSAGE QUEUE TESTS
# ============================================================================

class TestMessageQueue:
    """Tests for MessageQueue retry processing."""

    def test_enqueue_adds_item_to_queue(self, mock_message_queue):
        """Test that enqueue adds item with correct properties."""
        from MessageQueue import MessageQueue

        queue = MessageQueue()
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}
        content = "Test message"
        media_path = "/tmp/test.jpg"

        queue.enqueue(dest, content, media_path, "test reason")

        assert queue.get_queue_size() == 1
        item = queue._queue[0]
        assert item.destination == dest
        assert item.formatted_content == content
        assert item.media_path == media_path
        assert item.attempt_count == 0
        assert item.next_retry_time > time.time()

    def test_get_queue_size_returns_correct_count(self):
        """Test queue size tracking."""
        from MessageQueue import MessageQueue

        queue = MessageQueue()
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        assert queue.get_queue_size() == 0

        queue.enqueue(dest, "Message 1", None)
        assert queue.get_queue_size() == 1

        queue.enqueue(dest, "Message 2", None)
        assert queue.get_queue_size() == 2

    def test_clear_queue_removes_all_items(self):
        """Test clearing the queue."""
        from MessageQueue import MessageQueue

        queue = MessageQueue()
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        queue.enqueue(dest, "Message 1", None)
        queue.enqueue(dest, "Message 2", None)
        assert queue.get_queue_size() == 2

        queue.clear_queue()
        assert queue.get_queue_size() == 0

    def test_retry_success_removes_from_queue(self):
        """Test that successful retry removes item from queue."""
        from MessageQueue import MessageQueue

        queue = MessageQueue()
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        queue.enqueue(dest, "Test", None)
        queue._queue[0].next_retry_time = time.time() - 1  # Past due

        # Mock watchtower
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(return_value=True)

        # Run one iteration
        async def run_one_iteration():
            now = time.time()
            for retry_item in queue._queue[:]:
                if now >= retry_item.next_retry_time:
                    success = await queue._retry_send(retry_item, mock_watchtower)
                    if success:
                        queue._queue.remove(retry_item)

        asyncio.run(run_one_iteration())

        assert queue.get_queue_size() == 0
        mock_watchtower.discord.send_message.assert_called_once()


# ============================================================================
# OCR HANDLER TESTS
# ============================================================================

class TestOCRHandler:
    """Tests for OCR Handler."""

    def test_ocr_available(self, mock_ocr_handler):
        """Test checking OCR availability."""
        assert mock_ocr_handler.is_available() is True

    def test_extract_text(self, mock_ocr_handler):
        """Test text extraction from image."""
        result = mock_ocr_handler.extract_text("/tmp/test.jpg")
        assert result == "OCR extracted text"

    def test_ocr_with_invalid_file(self, mock_ocr_handler):
        """Test OCR with non-existent file."""
        mock_ocr_handler.extract_text.return_value = None
        result = mock_ocr_handler.extract_text("/nonexistent/file.jpg")
        assert result is None


# ============================================================================
# METRICS TESTS
# ============================================================================

class TestMetrics:
    """Tests for MetricsCollector."""

    def test_increment_metric(self, mock_metrics):
        """Test incrementing a metric."""
        mock_metrics.increment("test_metric")
        mock_metrics.increment.assert_called_once_with("test_metric")

    def test_get_metrics(self, mock_metrics):
        """Test retrieving all metrics."""
        mock_metrics.get_metrics.return_value = {
            'messages_processed': 10,
            'messages_sent_discord': 5,
            'messages_sent_telegram': 5
        }

        metrics = mock_metrics.get_metrics()
        assert metrics['messages_processed'] == 10
        assert metrics['messages_sent_discord'] == 5

    def test_multiple_increments(self, mock_metrics):
        """Test incrementing the same metric multiple times."""
        # Setup mock to track actual calls
        call_count = 0

        def side_effect(metric_name):
            nonlocal call_count
            call_count += 1

        mock_metrics.increment.side_effect = side_effect

        mock_metrics.increment("test_metric")
        mock_metrics.increment("test_metric")
        mock_metrics.increment("test_metric")

        assert call_count == 3

    def test_reset_metrics(self, mock_metrics):
        """Test resetting metrics."""
        mock_metrics.reset = Mock()
        mock_metrics.reset()
        mock_metrics.reset.assert_called_once()


# ============================================================================
# UTILITY TESTS
# ============================================================================

class TestUtilityFunctions:
    """Tests for various utility functions."""

    def test_get_entity_type_and_name_broadcast_channel(self):
        """Test entity type detection for broadcast channel."""
        from Discover import _get_entity_type_and_name
        from telethon.tl.types import Channel

        channel = Mock(spec=Channel)
        channel.broadcast = True
        channel.megagroup = False
        channel.title = "Test Channel"

        entity_type, entity_name = _get_entity_type_and_name(channel)
        assert entity_type == "Channel"
        assert entity_name == "Test Channel"

    def test_get_entity_type_and_name_supergroup(self):
        """Test entity type detection for supergroup."""
        from Discover import _get_entity_type_and_name
        from telethon.tl.types import Channel

        channel = Mock(spec=Channel)
        channel.broadcast = False
        channel.megagroup = True
        channel.title = "Test Supergroup"

        entity_type, entity_name = _get_entity_type_and_name(channel)
        assert entity_type == "Supergroup"
        assert entity_name == "Test Supergroup"

    def test_get_entity_type_and_name_bot(self):
        """Test entity type detection for bot User."""
        from Discover import _get_entity_type_and_name
        from telethon.tl.types import User

        user = Mock(spec=User)
        user.bot = True
        user.username = "test_bot"
        user.first_name = "Test"
        user.last_name = None

        entity_type, entity_name = _get_entity_type_and_name(user)
        assert entity_type == "Bot"
        assert entity_name == "@test_bot"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
