"""
MessageQueue - In-memory retry queue for rate-limited message delivery

This module provides a retry mechanism for messages that fail due to rate limiting
or temporary delivery errors. Uses exponential backoff strategy to avoid overwhelming
destination endpoints.

Features:
- Automatic retry with exponential backoff (5s, 10s, 20s)
- Maximum 3 retry attempts per message
- Async background processing
- Per-message attempt tracking

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
from logger_setup import setup_logger

if TYPE_CHECKING:
    from Watchtower import Watchtower

logger = setup_logger(__name__)


@dataclass
class RetryItem:
    """Minimal retry information for failed messages.

    Attributes:
        destination: Destination configuration dict
        formatted_content: Pre-formatted message text ready to send
        media_path: Optional path to media file attachment
        attempt_count: Number of retry attempts made (0-indexed)
        next_retry_time: Unix timestamp when next retry should occur
    """
    destination: Dict              # Destination config
    formatted_content: str         # Already formatted message content
    media_path: Optional[str]      # Path to media file
    attempt_count: int = 0         # Number of retry attempts
    next_retry_time: float = 0.0   # Timestamp when next retry should occur


class MessageQueue:
    """In-memory retry queue for rate-limited messages.

    Provides automatic retry with exponential backoff for failed message deliveries.
    Queue is processed by a background async task that attempts redelivery at
    appropriate intervals.
    """

    MAX_RETRIES = 3
    INITIAL_BACKOFF = 5  # seconds

    def __init__(self):
        """Initialize empty retry queue."""
        self._queue: List[RetryItem] = []

    def enqueue(self,
                destination: Dict,
                formatted_content: str,
                media_path: Optional[str],
                reason: str = "rate limit"):
        """Add failed message to retry queue.

        Args:
            destination: Destination configuration
            formatted_content: Already formatted message text
            media_path: Optional path to media file
            reason: Reason for failure (for logging)
        """
        retry_item = RetryItem(
            destination=destination,
            formatted_content=formatted_content,
            media_path=media_path,
            attempt_count=0,
            next_retry_time=time.time() + self.INITIAL_BACKOFF
        )
        self._queue.append(retry_item)
        logger.info(f"[MessageQueue] Enqueued message for retry: {reason} (destination: {destination['name']})")

    async def process_queue(self, watchtower: 'Watchtower') -> None:
        """Background task that continuously processes retry queue.

        Runs indefinitely as async background task. Checks queue every second and
        attempts to resend messages whose retry time has elapsed. Applies exponential
        backoff on failures (5s, 10s, 20s) and drops messages after MAX_RETRIES.

        Args:
            watchtower: Watchtower instance providing access to destination handlers
        """
        logger.info("[MessageQueue] Retry queue processor started")

        while True:
            now = time.time()

            # Iterate over copy to safely remove items during iteration
            for retry_item in self._queue[:]:
                if now >= retry_item.next_retry_time:
                    # Attempt retry
                    success = await self._retry_send(retry_item, watchtower)

                    if success:
                        self._queue.remove(retry_item)
                        logger.info(
                            f"[MessageQueue] Retry succeeded after {retry_item.attempt_count + 1} "
                            f"attempt(s) for {retry_item.destination['name']}"
                        )
                    elif retry_item.attempt_count >= self.MAX_RETRIES - 1:
                        # Max retries reached (0, 1, 2 = 3 attempts)
                        self._queue.remove(retry_item)
                        logger.error(
                            f"[MessageQueue] Message dropped after {self.MAX_RETRIES} "
                            f"failed attempts to {retry_item.destination['name']}"
                        )
                    else:
                        # Exponential backoff: 5s, 10s, 20s
                        retry_item.attempt_count += 1
                        backoff = self.INITIAL_BACKOFF * (2 ** retry_item.attempt_count)
                        retry_item.next_retry_time = now + backoff
                        logger.info(
                            f"[MessageQueue] Retry attempt {retry_item.attempt_count + 1}/{self.MAX_RETRIES} "
                            f"failed for {retry_item.destination['name']}, next retry in {backoff}s"
                        )

            await asyncio.sleep(1)  # Check queue every second

    async def _retry_send(self, retry_item: RetryItem, watchtower: 'Watchtower') -> bool:
        """Attempt to resend a message.

        Args:
            retry_item: Item to retry
            watchtower: Watchtower instance

        Returns:
            bool: True if successful, False otherwise
        """
        dest = retry_item.destination

        try:
            if dest['type'] == 'discord':
                return watchtower.discord.send_message(
                    retry_item.formatted_content,
                    dest['discord_webhook_url'],
                    retry_item.media_path
                )
            elif dest['type'] == 'telegram':
                # Telegram sending requires async
                channel_spec = dest['telegram_destination_channel']
                chat_id = await watchtower.telegram.resolve_destination(channel_spec)
                if chat_id:
                    result = await watchtower.telegram.send_copy(
                        chat_id,
                        retry_item.formatted_content,
                        retry_item.media_path
                    )
                    return result
                return False

        except Exception as e:
            logger.error(f"[MessageQueue] Retry send exception for {dest['name']}: {e}")
            return False

        return False

    def get_queue_size(self) -> int:
        """Get current queue size (for metrics/monitoring).

        Returns:
            int: Number of items in queue
        """
        return len(self._queue)

    def clear_queue(self) -> None:
        """Clear all items from queue (for graceful shutdown).

        Removes all pending retry items. Typically called during application
        shutdown to prevent orphaned retry attempts.
        """
        size = len(self._queue)
        self._queue.clear()
        if size > 0:
            logger.info(f"[MessageQueue] Cleared {size} items from retry queue")
