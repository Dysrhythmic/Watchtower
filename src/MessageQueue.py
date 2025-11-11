"""
MessageQueue - In-memory retry queue for rate limited message delivery

This module provides a retry mechanism for messages that fail due to rate limiting
or temporary delivery errors.

Retry Strategy:
    Attempt 1: Wait 5 seconds
    Attempt 2: Wait 10 seconds
    Attempt 3: Wait 20 seconds
    After 3 failures: Message is dropped and logged
"""
import time
import asyncio
from dataclasses import dataclass
from typing import List, Optional, Dict, TYPE_CHECKING
from LoggerSetup import setup_logger
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD

if TYPE_CHECKING:
    from Watchtower import Watchtower

_logger = setup_logger(__name__)


@dataclass
class RetryItem:
    """Minimal retry information for failed messages.

    Attributes:
        destination: Destination configuration dict
        formatted_content: Message text ready to send
        attachment_path: Optional path to media file attachment
        attempt_count: Number of retry attempts made (zero indexed)
        next_retry_time: Unix timestamp when next retry should occur
    """
    destination: Dict
    formatted_content: str
    attachment_path: Optional[str]
    attempt_count: int = 0
    next_retry_time: float = 0.0


class MessageQueue:
    """In-memory retry queue for rate limited messages.

    Provides automatic retry with exponential backoff for failed message deliveries.
    Queue is processed by a background async task that attempts redelivery.
    """

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 5  # seconds

    def __init__(self, metrics=None):
        """Initialize empty retry queue.

        Args:
            metrics: Optional MetricsCollector instance for tracking retry outcomes
        """
        self._queue: List[RetryItem] = []
        self._metrics = metrics

    def enqueue(self,
                destination: Dict,
                formatted_content: str,
                attachment_path: Optional[str],
                reason: str = "rate limit"):
        """Add failed message to retry queue."""
        retry_item = RetryItem(
            destination=destination,
            formatted_content=formatted_content,
            attachment_path=attachment_path,
            attempt_count=0,
            next_retry_time=time.time() + self.INITIAL_BACKOFF
        )
        self._queue.append(retry_item)
        _logger.info(f"Enqueued message for retry: {reason} (destination: {destination['name']})")

    async def process_queue(self, watchtower: 'Watchtower') -> None:
        """Background task that continuously processes retry queue.

        Runs indefinitely as async background task. Checks queue every second and
        attempts to resend messages whose retry time has elapsed.

        Args:
            watchtower: Watchtower instance providing access to destination handlers
        """
        _logger.info("Retry queue processor started")

        while True:
            now = time.time()

            # Iterate over copy to safely remove items during iteration
            for retry_item in self._queue[:]:
                if now >= retry_item.next_retry_time:
                    # Attempt retry
                    success = await self._retry_send(retry_item, watchtower)

                    if success:
                        self._queue.remove(retry_item)
                        if self._metrics:
                            self._metrics.increment("messages_retry_succeeded")
                        _logger.info(
                            f"Retry succeeded after {retry_item.attempt_count + 1} "
                            f"attempt(s) for {retry_item.destination['name']}"
                        )
                    # Max retries reached (0, 1, 2 = 3 attempts)
                    elif retry_item.attempt_count >= self.MAX_RETRIES - 1:
                        self._queue.remove(retry_item)
                        if self._metrics:
                            self._metrics.increment("messages_retry_failed")
                        _logger.error(
                            f"Message dropped after {self.MAX_RETRIES} "
                            f"failed attempts to {retry_item.destination['name']}"
                        )
                    # Exponential backoff: 5s, 10s, 20s
                    else:
                        retry_item.attempt_count += 1
                        backoff = self.INITIAL_BACKOFF * (2 ** retry_item.attempt_count)
                        retry_item.next_retry_time = now + backoff
                        _logger.info(
                            f"Retry attempt {retry_item.attempt_count + 1}/{self.MAX_RETRIES} "
                            f"failed for {retry_item.destination['name']}, next retry in {backoff}s"
                        )

            await asyncio.sleep(1)  # Check queue every second

    async def _retry_send(self, retry_item: RetryItem, watchtower: 'Watchtower') -> bool:
        """Attempt to resend a message.

        Args:
            retry_item: Message to retry
            watchtower: Watchtower instance

        Returns:
            bool: True if successful, False otherwise
        """
        dest = retry_item.destination

        try:
            if dest['type'] == APP_TYPE_DISCORD:
                return await watchtower.discord.send_message(
                    retry_item.formatted_content,
                    dest['discord_webhook_url'],
                    retry_item.attachment_path
                )
            elif dest['type'] == APP_TYPE_TELEGRAM:
                # Telegram sending requires async
                channel_spec = dest['telegram_dst_channel']
                chat_id = await watchtower.telegram.resolve_destination(channel_spec)
                if chat_id:
                    result = await watchtower.telegram.send_message(
                        retry_item.formatted_content,
                        chat_id,
                        retry_item.attachment_path
                    )
                    return result
                return False

        except Exception as e:
            _logger.error(f"Retry send exception for {dest['name']}: {e}")
            return False

        return False

    def get_queue_size(self) -> int:
        """Get current queue size.

        Returns:
            int: Number of items in queue
        """
        return len(self._queue)

    def clear_queue(self) -> None:
        """Clear all items from queue.

        Removes all pending retry items. Used for graceful shutdown.
        """
        size = len(self._queue)
        self._queue.clear()
        if size > 0:
            _logger.info(f"Cleared {size} items from retry queue")
