"""
DestinationHandler - Abstract base class for message delivery platforms

This module defines the common interface and shared functionality for all destination
handlers (Discord, Telegram, etc.). Provides rate limiting, text chunking, and
standardized message sending operations.

Current shared abstractions:
- Rate limit tracking and enforcement (preemptive waiting)
- Text chunking for platform message length limits
- Abstract interface for platform-specific implementations

Potential future abstractions:
- Media file validation (size, type checking)
- Retry logic with exponential backoff
- URL defanging utilities
- Logging standardization

Implementations:
    - DiscordHandler: Discord webhook delivery
    - TelegramHandler: Telethon API delivery
"""
import time
import math
from abc import ABC as AbstractBaseClass, abstractmethod
from typing import List, Dict, Optional
from logger_setup import setup_logger

_logger = setup_logger(__name__)


class DestinationHandler(AbstractBaseClass):
    """Abstract base class for destination handlers (Discord, Telegram, etc.).

    This class uses Python's Abstract Base Class (ABC) pattern to define an interface
    that all destination handlers must implement. Classes inheriting from this must implement
    all @abstractmethod decorated methods.

    Provides shared functionality for rate limiting and text chunking. Subclasses
    must implement platform-specific send and format operations.
    """

    def __init__(self):
        """Initialize handler with empty rate limit tracking."""
        # Track rate limits per destination: key -> expiry timestamp
        self._rate_limits: Dict[str, float] = {}

    @abstractmethod
    def _get_rate_limit_key(self, destination_identifier) -> str:
        """Get the unique key for rate limit tracking.

        This abstract method must be implemented by subclasses.
        The 'pass' statement is intentional, it's a template that subclasses override.

        Different platforms may have different rate limit bucketing strategies:
        - Discord: Rate limits per webhook URL
        - Telegram: Rate limits per chat_id

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram

        Returns:
            str: Unique key for this destination's rate limit bucket
        """
        pass

    def _check_and_wait_for_rate_limit(self, destination_identifier) -> None:
        """Check if destination is rate limited and wait if necessary.

        This method is called BEFORE attempting to send a message to check if we're
        still rate limited from a previous failed attempt.

        The actual rate limit detection happens in subclass implementations when they
        receive platform-specific error responses:
        - Discord: HTTP 429 with 'retry_after' header
        - Telegram: Error code 429 with 'retry_after' in response

        When a rate limit error is detected, subclasses call _store_rate_limit() to
        record the wait time, which this method then enforces on subsequent sends.

        Args:
            destination_identifier: webhook_url for Discord, chat_id for Telegram
        """
        key = self._get_rate_limit_key(destination_identifier)

        if key in self._rate_limits:
            wait_until = self._rate_limits[key]
            now = time.time()

            if now < wait_until:
                wait_time = wait_until - now
                _logger.info(f"[{self.__class__.__name__}] Rate limited, waiting {wait_time:.1f}s before sending")
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

        _logger.warning(
            f"[{self.__class__.__name__}] Rate limited: "
            f"retry_after={wait_seconds}s, waiting={rounded_wait}s"
        )

    def _chunk_text(self, text: str, max_length: int) -> List[str]:
        """Split text into chunks respecting max length and newline boundaries.

        Attempts to split at newlines when possible to preserve message structure.
        If no newline is found within max_length, performs hard split at max length.

        Args:
            text: Text to split into chunks
            max_length: Maximum characters per chunk

        Returns:
            List[str]: Text chunks, each <= max_length characters
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
                # No newline found, perform hard split at max_length
                split_point = max_length

            chunks.append(text[:split_point])
            text = text[split_point:].lstrip('\n')  # Remove leading newlines

        return chunks

    @abstractmethod
    def send_message(self, content: str, destination_identifier, media_path: Optional[str] = None) -> bool:
        """Send message to destination.

        This abstract method must be implemented by subclasses.
        The 'pass' statement is intentional, it's a template that subclasses override.

        Subclasses implement platform-specific sending logic:
        - Discord: POST to webhook URL with JSON payload
        - Telegram: Use Telethon API send methods

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

        This abstract method must be implemented by subclasses.
        The 'pass' statement is intentional, it's a template that subclasses override.

        Subclasses implement platform-specific formatting:
        - Discord: Markdown formatting
        - Telegram: HTML formatting

        Args:
            message_data: MessageData to format
            destination: Destination configuration

        Returns:
            str: Formatted message text
        """
        pass
