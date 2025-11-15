"""Tests for MessageQueue retry processing functionality."""
from unittest.mock import Mock, AsyncMock
import asyncio
import time
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageQueue import MessageQueue, RetryItem


def test_enqueue_adds_item_to_queue():
    """Test that enqueue adds item with correct properties."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}
    content = "Test message"
    attachment_path = "/tmp/test.jpg"

    queue.enqueue(dest, content, attachment_path, "test reason")

    assert queue.get_queue_size() == 1
    item = queue._queue[0]
    assert item.destination == dest
    assert item.formatted_content == content
    assert item.attachment_path == attachment_path
    assert item.attempt_count == 0
    assert item.next_retry_time > time.time()


def test_enqueue_sets_initial_backoff():
    """Test next_retry_time set to now + INITIAL_BACKOFF."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    now = time.time()
    queue.enqueue(dest, "Test", None)

    item = queue._queue[0]
    assert abs(item.next_retry_time - (now + 5)) < 0.1


def test_get_queue_size_returns_correct_count():
    """Test queue size tracking."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    assert queue.get_queue_size() == 0

    queue.enqueue(dest, "Message 1", None)
    assert queue.get_queue_size() == 1

    queue.enqueue(dest, "Message 2", None)
    assert queue.get_queue_size() == 2


def test_clear_queue_removes_all_items():
    """Test clearing the queue."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    queue.enqueue(dest, "Message 1", None)
    queue.enqueue(dest, "Message 2", None)
    assert queue.get_queue_size() == 2

    queue.clear_queue()
    assert queue.get_queue_size() == 0


def test_retry_success_removes_from_queue():
    """Test that successful retry removes item from queue."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    queue.enqueue(dest, "Test", None)
    queue._queue[0].next_retry_time = time.time() - 1

    mock_watchtower = Mock()
    mock_watchtower.discord = Mock()
    mock_watchtower.discord.send_message = AsyncMock(return_value=True)

    async def run_one_iteration():
        now = time.time()
        for retry_item in queue._queue[:]:
            if now >= retry_item.next_retry_time:
                success = await queue._retry_send(retry_item, mock_watchtower)
                if success:
                    queue._queue.remove(retry_item)

    asyncio.run(run_one_iteration())

    assert queue.get_queue_size() == 0
    mock_watchtower.discord.send_message.assert_called_once_with("Test", 'http://test', None)


def test_retry_failure_increments_attempt_count():
    """Test that retry failure increments attempt count and increases backoff."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    queue.enqueue(dest, "Test", None)
    queue._queue[0].next_retry_time = time.time() - 1

    mock_watchtower = Mock()
    mock_watchtower.discord = Mock()
    mock_watchtower.discord.send_message = AsyncMock(return_value=False)

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

    assert queue.get_queue_size() == 1
    item = queue._queue[0]
    assert item.attempt_count == 1
    assert abs(item.next_retry_time - (now + 10)) < 0.1


def test_max_retries_reached_drops_message():
    """Test that message is dropped when max retries reached."""
    queue = MessageQueue()
    dest = {'type': 'Discord', 'name': 'Test', 'discord_webhook_url': 'http://test'}

    queue.enqueue(dest, "Test", None)
    queue._queue[0].attempt_count = queue.MAX_RETRIES - 1
    queue._queue[0].next_retry_time = time.time() - 1

    mock_watchtower = Mock()
    mock_watchtower.discord = Mock()
    mock_watchtower.discord.send_message = AsyncMock(return_value=False)

    async def run_one_iteration():
        now = time.time()
        for retry_item in queue._queue[:]:
            if now >= retry_item.next_retry_time:
                success = await queue._retry_send(retry_item, mock_watchtower)
                if not success:
                    if retry_item.attempt_count >= queue.MAX_RETRIES - 1:
                        queue._queue.remove(retry_item)

    asyncio.run(run_one_iteration())

    assert queue.get_queue_size() == 0


def test_exponential_backoff_calculation():
    """Test exponential backoff follows pattern (5s, 10s, 20s)."""
    queue = MessageQueue()

    backoff_1 = queue.INITIAL_BACKOFF * (2 ** 1)
    assert backoff_1 == 10

    backoff_2 = queue.INITIAL_BACKOFF * (2 ** 2)
    assert backoff_2 == 20


def test_retry_send_discord_success():
    """Test successful Discord retry."""
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

    assert result
    mock_watchtower.discord.send_message.assert_called_once_with(
        "Test message", 'http://test', "/tmp/test.jpg"
    )


def test_retry_send_telegram_success():
    """Test successful Telegram retry."""
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

    assert result
    mock_watchtower.telegram.send_message.assert_called_once_with("Test message", 123456, None)


def test_retry_send_telegram_resolve_fails():
    """Test Telegram retry when resolve_destination fails."""
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

    assert not result


def test_retry_send_exception_caught(caplog):
    """Test exception handling during retry."""
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

    with caplog.at_level('ERROR'):
        result = asyncio.run(queue._retry_send(retry_item, mock_watchtower))

    assert not result
    assert any("Retry send exception" in msg for msg in caplog.text.split('\n'))


def test_long_rate_limit_doesnt_drop_message():
    """Test that rate limits longer than retry backoff don't cause message drops."""
    queue = MessageQueue()
    dest = {
        'type': 'Discord',
        'name': 'TestDiscord',
        'discord_webhook_url': 'http://test'
    }

    queue.enqueue(dest, "Test message", None, "test")
    assert queue.get_queue_size() == 1

    mock_watchtower = Mock()
    mock_watchtower.discord = Mock()
    mock_watchtower.discord._rate_limits = {
        'http://test': time.time() + 300
    }
    mock_watchtower.discord.send_message = AsyncMock(return_value=False)

    retry_item = queue._queue[0]
    retry_item.next_retry_time = time.time()

    async def process_once():
        now = time.time()
        for item in queue._queue[:]:
            if now >= item.next_retry_time:
                dest = item.destination
                rate_limit_expiry = None

                if dest['type'] == 'Discord':
                    webhook_url = dest['discord_webhook_url']
                    if webhook_url in mock_watchtower.discord._rate_limits:
                        rate_limit_expiry = mock_watchtower.discord._rate_limits[webhook_url]

                if rate_limit_expiry and now < rate_limit_expiry:
                    remaining = rate_limit_expiry - now
                    item.next_retry_time = rate_limit_expiry
                    return

                success = await queue._retry_send(item, mock_watchtower)
                if not success:
                    item.attempt_count += 1

    asyncio.run(process_once())

    assert queue.get_queue_size() == 1
    assert retry_item.attempt_count == 0

    expected_retry_time = mock_watchtower.discord._rate_limits['http://test']
    assert abs(retry_item.next_retry_time - expected_retry_time) < 1.0


def test_telegram_rate_limit_with_cached_chat_id():
    """Test Telegram rate limit checking with cached chat_id."""
    queue = MessageQueue()
    dest = {
        'type': 'Telegram',
        'name': 'TestTelegram',
        'telegram_dst_channel': '@testchannel',
        'telegram_dst_id': -1001234567890
    }

    queue.enqueue(dest, "Test message", None, "test")

    mock_watchtower = Mock()
    mock_watchtower.telegram = Mock()
    mock_watchtower.telegram._rate_limits = {
        -1001234567890: time.time() + 200
    }
    mock_watchtower.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    mock_watchtower.telegram.send_message = AsyncMock(return_value=False)

    retry_item = queue._queue[0]
    retry_item.next_retry_time = time.time()

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

    assert queue.get_queue_size() == 1
    assert retry_item.attempt_count == 0
