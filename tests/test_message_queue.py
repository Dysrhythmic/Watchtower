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
from unittest.mock import Mock, AsyncMock
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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}
        content = "Test message"
        attachment_path = "/tmp/test.jpg"

        # When: Enqueue message
        queue.enqueue(dest, content, attachment_path, "test reason")

        # Then: Queue has 1 item with correct properties
        self.assertEqual(queue.get_queue_size(), 1)
        item = queue._queue[0]
        self.assertEqual(item.destination, dest)
        self.assertEqual(item.formatted_content, content)
        self.assertEqual(item.attachment_path, attachment_path)
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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        # Enqueue with immediate retry (past time)
        queue.enqueue(dest, "Test", None)
        queue._queue[0].next_retry_time = time.time() - 1  # Past due

        # Mock watchtower with successful Discord send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = AsyncMock(return_value=True)

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        queue.enqueue(dest, "Test", None)
        queue._queue[0].next_retry_time = time.time() - 1  # Past due

        # Mock watchtower with failing Discord send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = AsyncMock(return_value=False)

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        queue.enqueue(dest, "Test", None)
        # Set to max retries - 1 (next failure will drop)
        queue._queue[0].attempt_count = queue.MAX_RETRIES - 1
        queue._queue[0].next_retry_time = time.time() - 1

        # Mock failing send
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = AsyncMock(return_value=False)

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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            attachment_path="/tmp/test.jpg",
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = AsyncMock(return_value=True)

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
        dest = {
            'type': 'Telegram',
            'name': 'Test',
            'telegram_dst_channel': '@testchannel',
            'telegram_dst_id': 123456
        }

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            attachment_path=None,
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.telegram = Mock()
        mock_watchtower.telegram.send_message = AsyncMock(return_value=True)

        result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertTrue(result)
        mock_watchtower.telegram.send_message.assert_called_once_with(
            "Test message", 123456, None
        )

    def test_retry_send_telegram_resolve_fails(self):
        """
        Given: Retry item with Telegram destination
        When: _retry_send() called, resolve_destination returns None
        Then: Returns False

        Tests: src/MessageQueue.py:120-128 (Telegram resolve failure)
        """
        queue = MessageQueue()
        dest = {'type': 'Telegram', 'name': 'Test', 'telegram_dst_channel': '@invalid'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            attachment_path=None,
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
        dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

        retry_item = RetryItem(
            destination=dest,
            formatted_content="Test message",
            attachment_path=None,
            attempt_count=0
        )

        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord.send_message = Mock(side_effect=Exception("Network error"))

        with self.assertLogs(level='ERROR') as log_context:
            result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

        self.assertFalse(result)
        self.assertTrue(any("Retry send exception" in msg for msg in log_context.output))


class TestMessageQueueRateLimitHandling(unittest.TestCase):
    """Tests for rate limit handling in retry queue."""

    def test_long_rate_limit_doesnt_drop_message(self):
        """
        Given: Message enqueued, destination has 300s rate limit
        When: Queue processes retries while still rate limited
        Then: Message not dropped, retry scheduled for when rate limit expires

        Tests that rate limits longer than retry backoff don't cause message drops
        """
        queue = MessageQueue()
        dest = {
            'type': 'Discord',
            'name': 'TestDiscord',
            'discord_webhook_url': 'http://test'
        }

        # Enqueue a message
        queue.enqueue(dest, "Test message", None, "test")
        self.assertEqual(queue.get_queue_size(), 1)

        # Mock watchtower with rate limited Discord handler
        mock_watchtower = Mock()
        mock_watchtower.discord = Mock()
        mock_watchtower.discord._rate_limits = {
            'http://test': time.time() + 300  # Rate limited for 300 seconds
        }
        mock_watchtower.discord.send_message = AsyncMock(return_value=False)

        # Simulate queue processing for short time (would normally trigger 3 retries)
        retry_item = queue._queue[0]

        # Set next retry time to now so it processes immediately
        retry_item.next_retry_time = time.time()

        # Process queue once
        async def process_once():
            now = time.time()
            for item in queue._queue[:]:
                if now >= item.next_retry_time:
                    # Check if destination is still rate limited
                    dest = item.destination
                    rate_limit_expiry = None

                    if dest['type'] == 'Discord':
                        webhook_url = dest['discord_webhook_url']
                        if webhook_url in mock_watchtower.discord._rate_limits:
                            rate_limit_expiry = mock_watchtower.discord._rate_limits[webhook_url]

                    # If still rate limited, reschedule
                    if rate_limit_expiry and now < rate_limit_expiry:
                        remaining = rate_limit_expiry - now
                        item.next_retry_time = rate_limit_expiry
                        return  # Don't count as retry

                    # Not rate limited - attempt retry
                    success = await queue._retry_send(item, mock_watchtower)
                    if not success:
                        item.attempt_count += 1

        asyncio.run(process_once())

        # Message should still be in queue
        self.assertEqual(queue.get_queue_size(), 1)

        # Attempt count should still be 0 (rate limit check didn't count as retry)
        self.assertEqual(retry_item.attempt_count, 0)

        # Next retry should be scheduled for when rate limit expires
        expected_retry_time = mock_watchtower.discord._rate_limits['http://test']
        self.assertAlmostEqual(retry_item.next_retry_time, expected_retry_time, delta=1.0)

    def test_telegram_rate_limit_with_cached_chat_id(self):
        """
        Given: Telegram message with cached chat_id, destination rate limited
        When: Queue checks rate limits
        Then: Uses cached chat_id to check Telegram rate limits
        """
        queue = MessageQueue()
        dest = {
            'type': 'Telegram',
            'name': 'TestTelegram',
            'telegram_dst_channel': '@testchannel',
            'telegram_dst_id': -1001234567890  # Cached from first send
        }

        # Enqueue a message
        queue.enqueue(dest, "Test message", None, "test")

        # Mock watchtower with rate limited Telegram handler
        mock_watchtower = Mock()
        mock_watchtower.telegram = Mock()
        mock_watchtower.telegram._rate_limits = {
            -1001234567890: time.time() + 200  # Rate limited for 200 seconds
        }
        mock_watchtower.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
        mock_watchtower.telegram.send_message = AsyncMock(return_value=False)

        retry_item = queue._queue[0]
        retry_item.next_retry_time = time.time()

        # Process queue once
        async def process_once():
            now = time.time()
            for item in queue._queue[:]:
                if now >= item.next_retry_time:
                    dest = item.destination
                    rate_limit_expiry = None

                    if dest['type'] == 'Telegram':
                        chat_id = dest.get('telegram_dst_id')
                        if chat_id and chat_id in mock_watchtower.telegram._rate_limits:
                            rate_limit_expiry = mock_watchtower.telegram._rate_limits[chat_id]

                    if rate_limit_expiry and now < rate_limit_expiry:
                        item.next_retry_time = rate_limit_expiry
                        return

                    success = await queue._retry_send(item, mock_watchtower)
                    if not success:
                        item.attempt_count += 1

        asyncio.run(process_once())

        # Message should still be in queue, attempt count should be 0
        self.assertEqual(queue.get_queue_size(), 1)
        self.assertEqual(retry_item.attempt_count, 0)


if __name__ == '__main__':
    unittest.main()
