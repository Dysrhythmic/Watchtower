"""
DestinationHandler - Abstract base class for message delivery platforms

This module defines the common interface and shared functionality for all destination
handlers (Discord, Telegram, etc.). Provides rate limiting, text chunking, and
standardized message sending operations. # <-- review: is there anything else that could be abstracted to this class?

Features:
- Automatic rate limit tracking and enforcement
- Text chunking for platform message length limits
- Abstract interface for platform-specific implementations

Implementations:
    - DiscordHandler: Discord webhook delivery
    - TelegramHandler: Telegram bot API delivery
"""
import time
import math
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from logger_setup import setup_logger

logger = setup_logger(__name__)


class DestinationHandler(ABC): # <-- review: Does this ensure it cannot be instantiated? Also, ABC is a bad name, can we import it as something more descriptive?
    """Abstract base class for destination handlers (Discord, Telegram, etc.).

    Provides shared functionality for rate limiting and text chunking. Subclasses
    must implement platform-specific send and format operations.
    """

    def __init__(self):
        """Initialize handler with empty rate limit tracking."""
        # Track rate limits per destination: key -> expiry timestamp
        self._rate_limits: Dict[str, float] = {}

    @abstractmethod
    def _get_rate_limit_key(self, destination_identifier) -> str: # <-- review: why does this exist if it does nothing?
        """Get the unique key for rate limit tracking.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram

        Returns:
            str: Unique key for this destination
        """
        pass

    def _check_and_wait_for_rate_limit(self, destination_identifier) -> None: # <-- review: when is this used? there are specific error codes or msgs that indicate when rate limits happen
        """Check if destination is rate limited and wait if necessary.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram
        """
        key = self._get_rate_limit_key(destination_identifier) # <-- review: this is calling a method that does nothing

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
        key = self._get_rate_limit_key(destination_identifier) # <-- review: this is calling a method that does nothing
        rounded_wait = math.ceil(wait_seconds)
        expires_at = time.time() + rounded_wait
        self._rate_limits[key] = expires_at

        logger.warning(
            f"[{self.__class__.__name__}] Rate limited: "
            f"retry_after={wait_seconds}s, waiting={rounded_wait}s"
        )

    def _chunk_text(self, text: str, max_length: int) -> List[str]:
        """Split text into chunks respecting max length and newline boundaries.

        Attempts to split at newlines when possible to preserve message structure.
        If no newline is found within max_length, performs hard split.

        Args:
            text: Text to split into chunks
            max_length: Maximum characters per chunk

        Returns:
            List[str]: Text chunks, each ≤ max_length characters

        Example:
            >>> handler._chunk_text("Line1\\nLine2\\nLine3", max_length=10)
            ["Line1", "Line2", "Line3"]
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            # Try to split at newline to preserve message structure
            split_point = text.rfind('\n', 0, max_length)
            if split_point == -1:
                # No newline found - perform hard split at max_length
                split_point = max_length

            chunks.append(text[:split_point])
            text = text[split_point:].lstrip('\n')  # Remove leading newlines

        return chunks

    @abstractmethod
    def send_message(self, content: str, destination_identifier, media_path: Optional[str] = None) -> bool: # <-- review: why does this exist if it does nothing?
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
    def format_message(self, message_data, destination: Dict) -> str: # <-- review: why does this exist if it does nothing?
        """Format message for this destination platform.

        Args:
            message_data: MessageData to format
            destination: Destination configuration

        Returns:
            str: Formatted message text
        """
        pass
