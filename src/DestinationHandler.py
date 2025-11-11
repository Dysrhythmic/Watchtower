"""
DestinationHandler - Supplies a common interface for destination handlers.

This module defines the common interface and shared functionality for all destination
handlers (Discord, Telegram, etc.). It provides rate limiting, text chunking, and
standardized message sending operations.

Current Implementations:
    - DiscordHandler
    - TelegramHandler
"""
import time
import math
from abc import ABC as AbstractBaseClass, abstractmethod
from typing import List, Dict, Optional
from LoggerSetup import setup_logger

_logger = setup_logger(__name__)


class DestinationHandler(AbstractBaseClass):
    """Abstract base class for destination handlers.

    This class uses Python's Abstract Base Class (ABC) pattern to define an interface
    that all destination handlers must implement. Classes inheriting from this must implement
    all @abstractmethod decorated methods.

    It also provides shared functionality for rate limiting and text chunking.
    Subclasses must implement platform-specific send and format operations.
    """

    def __init__(self):
        """Initialize with empty rate limit tracking."""
        # Track rate limits per destination: destination_id -> expiry timestamp
        self._rate_limits: Dict[str, float] = {}

    @property
    @abstractmethod
    def file_size_limit(self) -> int:
        """Maximum file size in bytes for this destination platform.

        Returns:
            int: Maximum file size in bytes
        """
        pass

    @abstractmethod
    def _extract_retry_after(self, error_or_response) -> Optional[float]:
        """Extract retry_after value from platform response.

        This method must be implemented by subclasses to parse platform specific
        rate limit responses and extract the number of seconds to wait before retrying.

        Args:
            error_or_response: Platform error or response object containing rate limit info. E.g.:
                              For Discord: requests.Response object with 429 status
                              For Telegram: FloodWaitError exception

        Returns:
            Optional[float]: Number of seconds to wait before retrying, or None if extraction fails
        """
        pass

    def _check_and_wait_for_rate_limit(self, destination_id) -> None:
        """Check if destination is rate limited and wait if necessary.

        This method is called before attempting to send a message to check if 
        there's still an ongoing rate limit from a previous failed attempt.

        The actual rate limit detection happens in subclass implementations when they
        receive platform-specific error responses. When a rate limit error is detected,
        subclasses call _store_rate_limit() to record the wait time, which this method
        then enforces on subsequent sends.
        """
        if destination_id in self._rate_limits:
            wait_until = self._rate_limits[destination_id]
            now = time.time()

            if now < wait_until:
                wait_time = wait_until - now
                _logger.info(f"[{self.__class__.__name__}] Rate limited, waiting {wait_time:.1f}s before sending")
                time.sleep(wait_time)
                # Clean up expired rate limit
                del self._rate_limits[destination_id]

    def _store_rate_limit(self, destination_id, wait_seconds: float) -> None:
        """Store rate limit information for a destination."""
        rounded_wait = math.ceil(wait_seconds)
        expires_at = time.time() + rounded_wait
        self._rate_limits[destination_id] = expires_at

        _logger.warning(
            f"[{self.__class__.__name__}] Rate limited: "
            f"retry_after={wait_seconds}s, waiting={rounded_wait}s"
        )

    def _chunk_text(self, text: str, max_length: int) -> List[str]:
        """Split text into chunks respecting max length and newline boundaries.

        Attempts to split at newlines when possible to preserve message structure.
        If no newline is found within max_length, performs hard split at max length.

        Raises:
            ValueError: If max_length isn't a positive value
        """
        if max_length < 0:
            raise ValueError("max_length must be positive")
        
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            split_point = text.rfind('\n', 0, max_length)
            if split_point == -1:
                # No newline found, perform hard split at max_length
                split_point = max_length

            chunks.append(text[:split_point])
            # Remove leading newlines
            text = text[split_point:].lstrip('\n')

        return chunks

    @abstractmethod
    async def send_message(self, content: str, destination_id, media_path: Optional[str] = None) -> bool:
        """Send message to destination.

        Subclasses implement platform-specific sending logic. E.g.:
        - Discord: POST to webhook URL with JSON payload
        - Telegram: Use Telethon API send methods
        """
        pass

    @abstractmethod
    def format_message(self, message_data, destination: Dict) -> str:
        """Format message for this destination platform.

        This abstract method must be implemented by subclasses
        to implement platform-specific formatting. E.g.:
        - Discord: Markdown formatting
        - Telegram: HTML formatting

        Args:
            message_data: MessageData to format
            destination: Destination configuration

        Returns:
            str: Formatted message
        """
        pass
