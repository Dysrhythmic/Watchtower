"""
DiscordHandler - Discord webhook message delivery

This module handles sending messages to Discord channels via webhooks. Implements
chunking for long messages, media attachment support, and rate limit handling.

Features:
- Automatic message chunking (2000 char Discord limit)
- Media file attachment support
- Rate limit detection and retry coordination
- Formatted message output with metadata headers

Discord API Details:
    - Max message length: 2000 characters
    - Rate limit response: 429 with retry_after in seconds
    - Success status codes: 200, 204
"""
import os
import json
import requests
from typing import Optional, Dict
from logger_setup import setup_logger
from MessageData import MessageData
from DestinationHandler import DestinationHandler

_logger = setup_logger(__name__)


class DiscordHandler(DestinationHandler):
    """Handles Discord webhook operations.

    Sends messages to Discord channels via webhook URLs. Automatically chunks
    long messages and handles rate limiting.
    """

    MAX_LENGTH = 2000  # Discord's message character limit
    AVATAR_URL = "https://raw.githubusercontent.com/Dysrhythmic/Watchtower/master/watchtower.png"

    def __init__(self):
        """Initialize Discord handler."""
        super().__init__()

    def _get_rate_limit_key(self, destination_identifier) -> str:
        """Get rate limit key for Discord (webhook URL)."""
        return str(destination_identifier)

    def send_message(self, content: str, webhook_url: str, media_path: Optional[str] = None) -> bool:
        """Send message to Discord webhook with automatic chunking.

        Sends media attachment with first chunk if media_path provided. Remaining
        chunks are sent as text-only messages. Returns False on any error (rate limit,
        network failure, invalid webhook).

        Args:
            content: Message text to send
            webhook_url: Discord webhook URL
            media_path: Optional path to media file attachment

        Returns:
            bool: True if all chunks sent successfully, False otherwise
        """
        try:
            # Check and wait for rate limit before sending
            self._check_and_wait_for_rate_limit(webhook_url)

            # Split content into 2000-char chunks
            chunks = self._chunk_text(content, self.MAX_LENGTH)
            chunks_sent = 0

            # Send first chunk with media attachment (if media exists)
            if media_path and os.path.exists(media_path):
                with open(media_path, 'rb') as f:
                    files = {'file': f}
                    data = {
                        'username': 'Watchtower',
                        'avatar_url': self.AVATAR_URL,
                        'content': chunks[0]
                    }
                    response = requests.post(webhook_url, files=files, data=data, timeout=15)

                    if response.status_code == 429:
                        self._handle_rate_limit(webhook_url, response)
                        return False
                    elif response.status_code not in [200, 204]:
                        body = (response.text or "")[:200]
                        _logger.error(
                            f"[DiscordHandler] Unsuccessful status code from Discord webhook (media): "
                            f"status={response.status_code}, body={body}"
                        )
                        return False
                    chunks_sent = 1  # First chunk sent with media

            # Send remaining chunks as text-only messages
            for chunk_index, chunk in enumerate(chunks[chunks_sent:], start=chunks_sent + 1):
                payload = {
                    "username": "Watchtower",
                    "avatar_url": self.AVATAR_URL,
                    "content": chunk
                }
                response = requests.post(webhook_url, json=payload, timeout=5)

                if response.status_code == 429:
                    self._handle_rate_limit(webhook_url, response)
                    return False
                elif response.status_code not in [200, 204]:
                    body = (response.text or "")[:200]
                    _logger.error(
                        f"[DiscordHandler] Unsuccessful status code from Discord webhook (chunk {chunk_index}/{len(chunks)}): "
                        f"status={response.status_code}, body={body}"
                    )
                    return False

            return True

        except Exception as e:
            _logger.error(f"[DiscordHandler] Discord send failed: {e}")
            return False

    def _handle_rate_limit(self, webhook_url: str, response: requests.Response) -> None:
        """Parse 429 rate limit response and store retry information.

        Discord returns rate limit info in JSON body with 'retry_after' field
        specifying seconds to wait. Falls back to 1 second if parsing fails.

        Args:
            webhook_url: Webhook URL being rate limited
            response: 429 HTTP response from Discord API
        """
        try:
            body = response.json()
            retry_after = body.get('retry_after', 1.0)
            self._store_rate_limit(webhook_url, retry_after)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback if response parsing fails
            _logger.warning(f"[DiscordHandler] Rate limited (429) but couldn't parse retry_after: {e}")
            self._store_rate_limit(webhook_url, 1.0)

    def format_message(self, message_data: MessageData, destination: Dict) -> str:
        """Format message for Discord with metadata headers and markdown formatting.

        Creates a formatted message with headers (source, sender, time), matched
        keywords, message text, and OCR text (quoted for visual distinction).

        Args:
            message_data: Message to format
            destination: Destination config (includes matched keywords)

        Returns:
            str: Formatted message ready for Discord delivery

        Format Structure:
            **New message from:** Channel Name
            **By:** Username
            **Time:** YYYY-MM-DD HH:MM:SS UTC
            **Source:** (defanged URL if available)
            **Content:** (media type if present)
            **Matched:** keyword1, keyword2
            **Message:**
            Message text content
            **OCR:**
            > Quoted OCR text
            > for visual distinction
        """
        lines = [
            f"**New message from:** {message_data.channel_name}",
            f"**By:** {message_data.username}",
            f"**Time:** {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]

        # Add defanged source URL if available (for CTI workflows)
        if 'src_url_defanged' in message_data.metadata:
            lines.append(f"**Source:** {message_data.metadata['src_url_defanged']}")

        if message_data.has_media:
            lines.append(f"**Content:** {message_data.media_type}")

        # Show which keywords triggered this message's delivery
        if destination.get('keywords'):
            lines.append(f"**Matched:** {', '.join(f'`{keyword}`' for keyword in destination['keywords'])}")

        if message_data.reply_context:
            lines.append(self._format_reply_context(message_data.reply_context))

        if message_data.text:
            lines.append(f"**Message:**\n{message_data.text}")

        # OCR text formatted as quote for visual distinction
        if message_data.ocr_raw:
            ocr_quoted = '\n'.join(f"> {line}" for line in message_data.ocr_raw.split('\n'))
            lines.append(f"**OCR:**\n{ocr_quoted}")

        return '\n'.join(lines)

    def _format_reply_context(self, reply_context: Dict) -> str:
        """Format Telegram reply-to information for Discord display.

        Shows author, timestamp, and content of the message being replied to.
        Truncates long text to 200 characters.

        Args:
            reply_context: Reply metadata dict with author, time, text, media info

        Returns:
            str: Formatted reply context section
        """
        parts = []
        parts.append(f"**  Replying to:** {reply_context['author']} ({reply_context['time']})")

        if reply_context.get('has_media'):
            media_type = reply_context.get('media_type', 'Other')
            parts.append(f"**  Original content:** {media_type}")

        original_text = reply_context.get('text', '')
        if original_text:
            # Truncate long replies for readability
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"**  Original message:** {original_text}")
        elif reply_context.get('has_media'):
            parts.append("**  Original message:** [Media only, no caption]")

        return '\n'.join(parts)
