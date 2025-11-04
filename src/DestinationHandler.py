import logging
import time
import math
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DestinationHandler(ABC):
    """Abstract base class for destination handlers (Discord, Telegram, etc.)."""

    def __init__(self):
        # Track rate limits per destination: key -> expiry timestamp
        self._rate_limits: Dict = {}

    @abstractmethod
    def _get_rate_limit_key(self, destination_identifier) -> str:
        """Get the unique key for rate limit tracking.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram

        Returns:
            str: Unique key for this destination
        """
        pass

    def _check_and_wait_for_rate_limit(self, destination_identifier) -> None:
        """Check if destination is rate limited and wait if necessary.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram
        """
        key = self._get_rate_limit_key(destination_identifier)

        if key in self._rate_limits:
            wait_until = self._rate_limits[key]
            now = time.time()

            if now < wait_until:
                wait_time = wait_until - now
                logger.info(f"[{self.__class__.__name__}] Rate limited, waiting {wait_time:.1f}s before sending")
                time.sleep(wait_time)
                # Clean up expired rate limit
                del self._rate_limits[key]

    def _store_rate_limit(self, destination_identifier, wait_seconds: float) -> None:
        """Store rate limit information for a destination.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram
            wait_seconds: How many seconds to wait before next attempt
        """
        key = self._get_rate_limit_key(destination_identifier)
        rounded_wait = math.ceil(wait_seconds)
        expires_at = time.time() + rounded_wait
        self._rate_limits[key] = expires_at

        logger.warning(
            f"[{self.__class__.__name__}] Rate limited: "
            f"retry_after={wait_seconds}s, waiting={rounded_wait}s"
        )

    def _chunk_text(self, text: str, max_length: int) -> List[str]:
        """Split text into chunks respecting max length.

        Args:
            text: Text to split
            max_length: Maximum characters per chunk

        Returns:
            List of text chunks
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            # Try to split at newline
            split_point = text.rfind('\n', 0, max_length)
            if split_point == -1:
                split_point = max_length

            chunks.append(text[:split_point])
            text = text[split_point:].lstrip('\n')

        return chunks

    @abstractmethod
    def send_message(self, content: str, destination_identifier, media_path: Optional[str] = None) -> bool:
        """Send message to destination.

        Args:
            content: Message text to send
            destination_identifier: webhook_url for Discord, chat_id for Telegram
            media_path: Optional path to media file attachment

        Returns:
            bool: True if successful, False otherwise
        """
        pass

    @abstractmethod
    def format_message(self, message_data, destination: Dict) -> str:
        """Format message for this destination platform.

        Args:
            message_data: MessageData to format
            destination: Destination configuration

        Returns:
            str: Formatted message text
        """
        pass
