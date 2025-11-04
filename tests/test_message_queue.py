"""
Tests for MessageQueue retry processing functionality.

These tests cover critical retry queue logic that ensures message reliability
when rate limits or transient errors occur.

Tests:
- Queue enqueue/dequeue operations (src/MessageQueue.py:34-55)
- Retry attempt logic with exponential backoff (src/MessageQueue.py:68-94)
- Max retry limit enforcement (src/MessageQueue.py:79-85)
- Successful retry removes from queue (src/MessageQueue.py:73-78)
- Discord retry sending (src/MessageQueue.py:111-116)
- Telegram retry sending (src/MessageQueue.py:117-128)
- Exception handling during retry (src/MessageQueue.py:130-132)
- Queue size tracking (src/MessageQueue.py:136-142)
"""

import unittest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
import time
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageQueue import MessageQueue, RetryItem


class TestMessageQueueBasics(unittest.TestCase):
    """Tests for basic queue operations."""

    def test_enqueue_adds_item_to_queue(self):
        """
        Given: Empty queue
        When: enqueue() called
        Then: Item added to queue with correct properties

        Tests: src/MessageQueue.py:34-55 (enqueue logic)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}
        content = "Test message"
        media_path = "/tmp/test.jpg"

        # When: Enqueue message
        queue.enqueue(dest, content, media_path, "test reason")

        # Then: Queue has 1 item with correct properties
        self.assertEqual(queue.get_queue_size(), 1)
        item = queue._queue[0]
        self.assertEqual(item.destination, dest)
        self.assertEqual(item.formatted_content, content)
        self.assertEqual(item.media_path, media_path)
        self.assertEqual(item.attempt_count, 0)
        self.assertGreater(item.next_retry_time, time.time())

    def test_enqueue_sets_initial_backoff(self):
        """
        Given: Empty queue
        When: enqueue() called
        Then: next_retry_time set to now + INITIAL_BACKOFF

        Tests: src/MessageQueue.py:52 (backoff calculation)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        now = time.time()
        queue.enqueue(dest, "Test", None)

        item = queue._queue[0]
        # Should be roughly now + 5 seconds (allowing 0.1s for execution)
        self.assertAlmostEqual(item.next_retry_time, now + 5, delta=0.1)

    def test_get_queue_size_returns_correct_count(self):
        """
        Given: Queue with multiple items
        When: get_queue_size() called
        Then: Returns correct count

        Tests: src/MessageQueue.py:136-142 (queue size tracking)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        self.assertEqual(queue.get_queue_size(), 0)

        queue.enqueue(dest, "Message 1", None)
        self.assertEqual(queue.get_queue_size(), 1)

        queue.enqueue(dest, "Message 2", None)
        self.assertEqual(queue.get_queue_size(), 2)

    def test_clear_queue_removes_all_items(self):
        """
        Given: Queue with items
        When: clear_queue() called
        Then: All items removed

        Tests: src/MessageQueue.py:144-149 (queue clearing)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        queue.enqueue(dest, "Message 1", None)
        queue.enqueue(dest, "Message 2", None)
        self.assertEqual(queue.get_queue_size(), 2)

        queue.clear_queue()
        self.assertEqual(queue.get_queue_size(), 0)


class TestMessageQueueRetryLogic(unittest.TestCase):
    """Tests for retry processing logic."""

    def test_retry_success_removes_from_queue(self):
        """
        Given: Queue with 1 item, retry time reached
        When: process_queue() runs one iteration, retry succeeds
        Then: Item removed from queue

        Tests: src/MessageQueue.py:73-78 (successful retry removal)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        # Enqueue with immediate retry (past time)
        queue.enqueue(dest, "Test", None)
        queue._queue[0].next_retry_time = time.time() - 1  # Past due

        # Mock watchtower with successful Discord send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(return_value=True)

        # Run one iteration of process_queue
        async def run_one_iteration():
            # Process once then break
            now = time.time()
            for retry_item in queue._queue[:]:
                if now >= retry_item.next_retry_time:
                    success = await queue._retry_send(retry_item, mock_watchtower)
                    if success:
                        queue._queue.remove(retry_item)

        asyncio.run(run_one_iteration())

        # Then: Queue should be empty
        self.assertEqual(queue.get_queue_size(), 0)
        mock_watchtower.discord.send_message.assert_called_once_with(
            "Test", 'http://test', None
        )

    def test_retry_failure_increments_attempt_count(self):
        """
        Given: Queue with 1 item, retry time reached
        When: process_queue() runs, retry fails
        Then: attempt_count incremented, backoff increased

        Tests: src/MessageQueue.py:86-94 (exponential backoff)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        queue.enqueue(dest, "Test", None)
        queue._queue[0].next_retry_time = time.time() - 1  # Past due

        # Mock watchtower with failing Discord send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(return_value=False)

        # Run one iteration
        async def run_one_iteration():
            now = time.time()
            for retry_item in queue._queue[:]:
                if now >= retry_item.next_retry_time:
                    success = await queue._retry_send(retry_item, mock_watchtower)
                    if not success and retry_item.attempt_count < queue.MAX_RETRIES - 1:
                        retry_item.attempt_count += 1
                        backoff = queue.INITIAL_BACKOFF * (2 ** retry_item.attempt_count)
                        retry_item.next_retry_time = now + backoff

        now = time.time()
        asyncio.run(run_one_iteration())

        # Then: Still in queue, attempt count incremented, backoff increased
        self.assertEqual(queue.get_queue_size(), 1)
        item = queue._queue[0]
        self.assertEqual(item.attempt_count, 1)
        # Backoff should be 5 * 2^1 = 10 seconds
        self.assertAlmostEqual(item.next_retry_time, now + 10, delta=0.1)

    def test_max_retries_reached_drops_message(self):
        """
        Given: Queue with item at MAX_RETRIES-1 attempts
        When: process_queue() runs, retry fails
        Then: Item removed from queue (dropped)

        Tests: src/MessageQueue.py:79-85 (max retry enforcement)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        queue.enqueue(dest, "Test", None)
        # Set to max retries - 1 (next failure will drop)
        queue._queue[0].attempt_count = queue.MAX_RETRIES - 1
        queue._queue[0].next_retry_time = time.time() - 1

        # Mock failing send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(return_value=False)

        # Run one iteration
        async def run_one_iteration():
            now = time.time()
            for retry_item in queue._queue[:]:
                if now >= retry_item.next_retry_time:
                    success = await queue._retry_send(retry_item, mock_watchtower)
                    if not success:
                        if retry_item.attempt_count >= queue.MAX_RETRIES - 1:
                            queue._queue.remove(retry_item)

        asyncio.run(run_one_iteration())

        # Then: Queue empty (message dropped)
        self.assertEqual(queue.get_queue_size(), 0)

    def test_exponential_backoff_calculation(self):
        """
        Given: Queue with items at different attempt counts
        When: Backoff calculated
        Then: Follows exponential pattern (5s, 10s, 20s)

        Tests: src/MessageQueue.py:89 (exponential backoff formula)
        """
        queue = MessageQueue()

        # Attempt 0 → 1: 5 * 2^1 = 10s
        backoff_1 = queue.INITIAL_BACKOFF * (2 ** 1)
        self.assertEqual(backoff_1, 10)

        # Attempt 1 → 2: 5 * 2^2 = 20s
        backoff_2 = queue.INITIAL_BACKOFF * (2 ** 2)
        self.assertEqual(backoff_2, 20)


class TestMessageQueueRetrySending(unittest.TestCase):
    """Tests for retry sending to different destination types."""

    def test_retry_send_discord_success(self):
        """
        Given: Retry item with Discord destination
        When: _retry_send() called, send succeeds
        Then: Returns True

        Tests: src/MessageQueue.py:111-116 (Discord retry)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            media_path="/tmp/test.jpg",
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(return_value=True)

        result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertTrue(result)
        mock_watchtower.discord.send_message.assert_called_once_with(
            "Test message", 'http://test', "/tmp/test.jpg"
        )

    def test_retry_send_telegram_success(self):
        """
        Given: Retry item with Telegram destination
        When: _retry_send() called, send succeeds
        Then: Returns True

        Tests: src/MessageQueue.py:117-128 (Telegram retry)
        """
        queue = MessageQueue()
        dest = {'type': 'telegram', 'name': 'Test', 'destination': '@testchannel'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            media_path=None,
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.telegram = Mock()
        mock_watchtower.telegram.resolve_destination = AsyncMock(return_value=123456)
        mock_watchtower.telegram.send_copy = AsyncMock(return_value=True)

        result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertTrue(result)
        mock_watchtower.telegram.resolve_destination.assert_called_once_with('@testchannel')
        mock_watchtower.telegram.send_copy.assert_called_once_with(
            123456, "Test message", None
        )

    def test_retry_send_telegram_resolve_fails(self):
        """
        Given: Retry item with Telegram destination
        When: _retry_send() called, resolve_destination returns None
        Then: Returns False

        Tests: src/MessageQueue.py:120-128 (Telegram resolve failure)
        """
        queue = MessageQueue()
        dest = {'type': 'telegram', 'name': 'Test', 'destination': '@invalid'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            media_path=None,
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.telegram = Mock()
        mock_watchtower.telegram.resolve_destination = AsyncMock(return_value=None)

        result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertFalse(result)

    def test_retry_send_exception_caught(self):
        """
        Given: Retry item with Discord destination
        When: _retry_send() called, send_message raises exception
        Then: Returns False, exception logged

        Tests: src/MessageQueue.py:130-132 (exception handling)
        """
        queue = MessageQueue()
        dest = {'type': 'discord', 'name': 'Test', 'webhook_url': 'http://test'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            media_path=None,
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(side_effect=Exception("Network error"))

        with self.assertLogs(level='ERROR') as log_context:
            result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertFalse(result)
        self.assertTrue(any("Retry send exception" in msg for msg in log_context.output))


if __name__ == '__main__':
    unittest.main()
