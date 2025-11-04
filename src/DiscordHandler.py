import logging
import os
import json
import requests
from typing import Optional, Dict
from MessageData import MessageData
from DestinationHandler import DestinationHandler

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DiscordHandler(DestinationHandler):
    """Handles Discord webhook operations."""

    MAX_LENGTH = 2000

    def __init__(self):
        super().__init__()

    def _get_rate_limit_key(self, destination_identifier) -> str:
        """Get rate limit key for Discord (webhook URL)."""
        return str(destination_identifier)

    def send_message(self, content: str, webhook_url: str, media_path: Optional[str] = None) -> bool:
        """Send message to Discord webhook.

        Args:
            content: Message text to send
            webhook_url: Discord webhook URL
            media_path: Optional path to media file attachment

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check and wait for rate limit
            self._check_and_wait_for_rate_limit(webhook_url)

            chunks = self._chunk_text(content, self.MAX_LENGTH)
            chunks_sent = 0

            if media_path and os.path.exists(media_path):
                with open(media_path, 'rb') as f:
                    files = {'file': f}
                    data = {'username': 'Watchtower', 'content': chunks[0]}
                    response = requests.post(webhook_url, files=files, data=data, timeout=15)
                    if response.status_code == 429:
                        self._handle_rate_limit(webhook_url, response)
                        return False
                    elif response.status_code not in [200, 204]:
                        body = (response.text or "")[:200]
                        logger.error(
                            f"[DiscordHandler] Unsuccessful status code from Discord webhook (media): "
                            f"status={response.status_code}, body={body}"
                        )
                        return False
                    chunks_sent = 1

            for chunk_index, chunk in enumerate(chunks[chunks_sent:], start=chunks_sent + 1):
                payload = {"username": "Watchtower", "content": chunk}
                response = requests.post(webhook_url, json=payload, timeout=5)
                if response.status_code == 429:
                    self._handle_rate_limit(webhook_url, response)
                    return False
                elif response.status_code not in [200, 204]:
                    body = (response.text or "")[:200]
                    logger.error(
                        f"[DiscordHandler] Unsuccessful status code from Discord webhook (chunk {chunk_index}/{len(chunks)}): "
                        f"status={response.status_code}, body={body}"
                    )
                    return False
            return True

        except Exception as e:
            logger.error(f"[DiscordHandler] Discord send failed: {e}")
            return False

    def _handle_rate_limit(self, webhook_url: str, response: requests.Response) -> None:
        """Parse 429 response and store rate limit."""
        try:
            body = response.json()
            retry_after = body.get('retry_after', 1.0)
            self._store_rate_limit(webhook_url, retry_after)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Fallback if response parsing fails
            logger.warning(f"[DiscordHandler] Rate limited (429) but couldn't parse retry_after: {e}")
            self._store_rate_limit(webhook_url, 1.0)

    def format_message(self, message_data: MessageData, destination: Dict) -> str:
        """Format message for Discord (Telegram copy-mode should mirror this)."""
        lines = [
            f"**New message from:** {message_data.channel_name}",
            f"**By:** {message_data.username}",
            f"**Time:** {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]

        # Add defanged source URL if available
        if 'src_url_defanged' in message_data.metadata:
            lines.append(f"**Source:** {message_data.metadata['src_url_defanged']}")

        if message_data.has_media:
            lines.append(f"**Content:** {message_data.media_type}")

        if destination.get('keywords'):
            lines.append(f"**Matched:** {', '.join(f'`{keyword}`' for keyword in destination['keywords'])}")

        if message_data.reply_context:
            lines.append(self._format_reply_context(message_data.reply_context))

        if message_data.text:
            lines.append(f"**Message:**\n{message_data.text}")

        # OCR raw text (if present) - formatted as quote for visual distinction
        if message_data.ocr_raw:
            ocr_quoted = '\n'.join(f"> {line}" for line in message_data.ocr_raw.split('\n'))
            lines.append(f"**OCR:**\n{ocr_quoted}")

        return '\n'.join(lines)

    def _format_reply_context(self, reply_context: Dict) -> str:
        """Format reply context for Discord display."""
        parts = []
        parts.append(f"**  Replying to:** {reply_context['author']} ({reply_context['time']})")

        if reply_context.get('has_media'):
            media_type = reply_context.get('media_type', 'Other')
            parts.append(f"**  Original content:** {media_type}")

        original_text = reply_context.get('text', '')
        if original_text:
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"**  Original message:** {original_text}")
        elif reply_context.get('has_media'):
            parts.append("**  Original message:** [Media only, no caption]")

        return '\n'.join(parts)
