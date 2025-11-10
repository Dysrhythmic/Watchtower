"""
DiscordHandler - Discord webhook message delivery

This module handles sending messages to Discord channels via webhooks. Implements
chunking for long messages, media attachment support, and rate limit handling.

Discord API Details:
    - Max message length: 2000 characters
    - Rate limit response: 429 status code with retry_after in seconds
    - Success status codes: 200, 204
"""
import os
import json
import requests
from typing import Optional, Dict
from LoggerSetup import setup_logger
from MessageData import MessageData
from DestinationHandler import DestinationHandler

_logger = setup_logger(__name__)


class DiscordHandler(DestinationHandler):
    """Handles Discord webhook operations.

    Sends messages to Discord channels via webhook URLs. Automatically chunks
    long messages and handles rate limiting.
    """

    _USERNAME = 'Watchtower'
    _AVATAR_URL = "https://raw.githubusercontent.com/Dysrhythmic/Watchtower/master/watchtower.png"
    _FILE_SIZE_LIMIT = 25 * 1024 * 1024  # 25MB for Discord free tier
    MAX_MSG_LENGTH = 2000

    def __init__(self):
        super().__init__()

    @property
    def file_size_limit(self) -> int:
        """Maximum file size in bytes for Discord."""
        return self._FILE_SIZE_LIMIT

    def send_message(self, content: str, webhook_url: str, attachment_path: Optional[str] = None) -> bool:
        """Send message to Discord webhook.

        Sends attachment file with first chunk if attachment_path provided. Remaining
        chunks are sent as text-only messages. Returns False on any error (rate limit,
        network failure, invalid webhook).

        Args:
            content: Message text to send
            webhook_url: Discord webhook URL
            attachment_path: Optional path to attachment file

        Returns:
            bool: True if all chunks sent successfully, False otherwise
        """
        try:
            self._check_and_wait_for_rate_limit(webhook_url)

            chunks = self._chunk_text(content, self.MAX_MSG_LENGTH)
            chunks_sent = 0

            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, 'rb') as f:
                    files = {'file': f}
                    data = {
                        'username': self._USERNAME,
                        'avatar_url': self._AVATAR_URL,
                        'content': chunks[0]
                    }
                    response = requests.post(webhook_url, files=files, data=data, timeout=15)

                    if response.status_code == 429:
                        self._handle_rate_limit(webhook_url, response)
                        return False
                    elif response.status_code not in [200, 204]:
                        body = (response.text or "")[:200]
                        _logger.error(
                            f"Unsuccessful status code from Discord webhook (sent media): "
                            f"status={response.status_code}, body={body}"
                        )
                        return False
                    chunks_sent = 1  # First chunk sent with media

            # Send remaining chunks as text-only messages
            for chunk_index, chunk in enumerate(chunks[chunks_sent:], start=chunks_sent + 1):
                payload = {
                    "username": self._USERNAME,
                    "avatar_url": self._AVATAR_URL,
                    "content": chunk
                }
                response = requests.post(webhook_url, json=payload, timeout=5)

                if response.status_code == 429:
                    self._handle_rate_limit(webhook_url, response)
                    return False
                elif response.status_code not in [200, 204]:
                    body = (response.text or "")[:200]
                    _logger.error(
                        f"Unsuccessful status code from Discord webhook (chunk {chunk_index}/{len(chunks)}): "
                        f"status={response.status_code}, body={body}"
                    )
                    return False

            return True

        except Exception as e:
            _logger.error(f"Discord send failed: {e}")
            return False

    def _extract_retry_after(self, response: requests.Response) -> Optional[float]:
        """Extract retry_after value from Discord 429 rate limit response.

        Discord returns rate limit info in JSON body with 'retry_after' field
        specifying seconds to wait.

        Args:
            response: 429 HTTP response from Discord API

        Returns:
            Optional[float]: Retry after seconds if successfully extracted, None if parsing fails
        """
        try:
            body = response.json()
            return body.get('retry_after', 1.0)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _logger.warning(f"Rate limited (429) but couldn't parse retry_after: {e}")
            return None

    def _handle_rate_limit(self, webhook_url: str, response: requests.Response) -> None:
        """Parse 429 rate limit response and store retry information.

        Args:
            webhook_url: Webhook URL being rate limited
            response: 429 HTTP response from Discord API
        """
        retry_after = self._extract_retry_after(response)
        if retry_after is None:
            retry_after = 1.0  # Fallback if extraction fails
        self._store_rate_limit(webhook_url, retry_after)

    def format_message(self, message_data: MessageData, destination: Dict) -> str:
        """Format message for Discord with metadata and markdown formatting.

        Creates a formatted message with metadata (source, sender, time),
        matched keywords, message text, and OCR text.

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
            **Matched:** keyword1, keyword2 (if any)
            **Message:**
            Message text content
            **OCR:**
            > Quoted OCR text
        """
        lines = [
            f"**New message from:** {message_data.channel_name}",
            f"**By:** {message_data.username}",
            f"**Time:** {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]

        if 'src_url_defanged' in message_data.metadata:
            lines.append(f"**Source:** {message_data.metadata['src_url_defanged']}")

        if message_data.has_attachments:
            lines.append(f"**Content:** {message_data.attachment_type}")

        if destination.get('keywords'):
            lines.append(f"**Matched:** {', '.join(f'`{keyword}`' for keyword in destination['keywords'])}")

        if message_data.reply_context:
            lines.append(self._format_reply_context(message_data.reply_context))

        if message_data.text:
            lines.append(f"**Message:**\n{message_data.text}")

        if message_data.ocr_raw:
            ocr_quoted = '\n'.join(f"> {line}" for line in message_data.ocr_raw.split('\n'))
            lines.append(f"**OCR:**\n{ocr_quoted}")

        return '\n'.join(lines)

    def _format_reply_context(self, reply_context: Dict) -> str:
        """Format source reply-to information for Discord display.

        Shows author, timestamp, and content of the message being replied to.
        Truncates long text to 200 characters.

        Args:
            reply_context: Reply metadata dict with author, time, text, media info

        Returns:
            str: Formatted reply context section
        """
        parts = []
        parts.append(f"**  Replying to:** {reply_context['author']} ({reply_context['time']})")

        if reply_context.get('has_attachments'):
            attachment_type = reply_context.get('attachment_type', 'Other')
            parts.append(f"**  Original content:** {attachment_type}")

        original_text = reply_context.get('text', '')
        if original_text:
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"**  Original message:** {original_text}")
        elif reply_context.get('has_attachments'):
            parts.append("**  Original message:** [Attachment only, no caption]")

        return '\n'.join(parts)
