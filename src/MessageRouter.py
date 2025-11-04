import logging
from typing import List, Dict, Optional
from ConfigManager import ConfigManager
from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MessageRouter:
    """Routes messages to destinations based on configuration."""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.channel_mappings = {}

    def is_channel_restricted(self, channel_id: str, channel_name: str) -> bool:
        """Check if any destination has restricted mode enabled for this channel."""
        for webhook in self.config.webhooks:
            for channel in webhook['channels']:
                if self._channel_matches(channel_id, channel_name, channel['id']):
                    if channel.get('restricted_mode', False):
                        return True
        return False

    def is_ocr_enabled_for_channel(self, channel_id: str, channel_name: str) -> bool:
        """Check if any destination has OCR enabled for this channel."""
        for webhook in self.config.webhooks:
            for channel in webhook['channels']:
                if self._channel_matches(channel_id, channel_name, channel['id']):
                    if channel.get('ocr', False):
                        return True
        return False

    def add_channel_mapping(self, config_id: str, actual_id: str):
        """Store mapping between configured ID and actual channel ID."""
        self.channel_mappings[config_id] = actual_id

    def get_destinations(self, message_data: MessageData) -> List[Dict]:
        """Find all destinations that should receive this message based on keyword matching.

        Matches message text and OCR text against configured keywords for each source channel.
        Returns destination configs with matched keywords included for display.

        Args:
            message_data: The message to route

        Returns:
            List of destination configs with matched keywords
        """
        destinations: List[Dict] = []

        # Determine if this channel appears anywhere in config
        channel_is_configured = False
        for webhook in self.config.webhooks:
            for channel in webhook.get('channels', []):
                if self._channel_matches(message_data.channel_id, message_data.channel_name, channel['id']):
                    channel_is_configured = True
                    break
            if channel_is_configured:
                break

        # If the channel isn't configured, log and return empty
        if not channel_is_configured:
            logger.info(f"[MessageRouter] No configured matches for channel {message_data.channel_name} ({message_data.channel_id})")
            return destinations

        # Otherwise collect destinations
        for webhook in self.config.webhooks:
            # Find matching channel config for this destination
            channel_config = None
            for channel in webhook['channels']:
                if self._channel_matches(message_data.channel_id, message_data.channel_name, channel['id']):
                    channel_config = channel
                    break
            if not channel_config:
                continue

            # Build searchable text for keyword matching: message text + OCR text (if enabled & present)
            searchable_text = message_data.text or ""
            if channel_config.get('ocr', False) and message_data.ocr_raw:
                searchable_text = f"{searchable_text}\n{message_data.ocr_raw}" if searchable_text else message_data.ocr_raw

            keywords = channel_config.get('keywords')
            if not keywords:
                # No keywords -> forward all
                destinations.append(self._make_dest_entry(webhook, channel_config, matched=[]))
            elif searchable_text:
                matched = [kw for kw in keywords if kw.lower() in searchable_text.lower()]
                if matched:
                    destinations.append(self._make_dest_entry(webhook, channel_config, matched=matched))

        return destinations

    def parse_msg(self, message_data: MessageData, parser_config: Optional[Dict]) -> MessageData:
        """Apply text parsing rules to message.

        Parser trims lines from beginning/end of message text using dictionary format:
        {"trim_front_lines": N, "trim_back_lines": M}

        Args:
            message_data: Original message
            parser_config: Parser configuration dict with trim_front_lines and trim_back_lines keys

        Returns:
            New MessageData with modified text
        """
        text = message_data.text or ""
        if not text:
            return message_data

        # Dict config: trim from both ends
        if isinstance(parser_config, dict):
            front = int(parser_config.get('trim_front_lines', 0) or 0)
            back = int(parser_config.get('trim_back_lines', 0) or 0)

            # Validate values
            if front < 0 or back < 0:
                logger.warning(f"[MessageRouter] Invalid parser config: values must be >= 0, got front={front}, back={back}")
                return message_data

            # Skip parsing if both are 0
            if front == 0 and back == 0:
                return message_data

            lines = text.split('\n')
            if front > 0:
                lines = lines[front:]
            if back > 0:
                lines = lines[:-back]
            new_text = '\n'.join(lines)
            if not new_text:
                parts = []
                if front > 0: parts.append(f"first {front}")
                if back > 0: parts.append(f"last {back}")
                hint = " and ".join(parts) if parts else "all"
                new_text = f"**[Message content removed by parser: {hint} line(s) stripped]**"
            return MessageData(
                source_type=message_data.source_type,
                channel_id=message_data.channel_id,
                channel_name=message_data.channel_name,
                username=message_data.username,
                timestamp=message_data.timestamp,
                text=new_text,
                has_media=message_data.has_media,
                media_type=message_data.media_type,
                media_path=message_data.media_path,
                reply_context=message_data.reply_context,
                original_message=message_data.original_message,
                ocr_enabled=message_data.ocr_enabled,
                ocr_raw=message_data.ocr_raw,
                metadata=message_data.metadata
            )

        # Invalid or None - return unchanged
        if parser_config is not None:
            logger.warning(f"[MessageRouter] Invalid parser config type: {type(parser_config)}, expected dict or None")
        return message_data

    def _make_dest_entry(self, webhook: Dict, channel_config: Dict, matched: List[str]) -> Dict:
        """Normalize destination entry."""
        base = {
            'name': webhook['name'],
            'type': webhook.get('type', 'discord'),
            'keywords': matched,
            'restricted_mode': channel_config.get('restricted_mode', False),
            'parser': channel_config.get('parser'),
            'ocr': channel_config.get('ocr', False),
        }
        if base['type'] == 'discord':
            base['webhook_url'] = webhook['webhook_url']
        else:
            base['destination'] = webhook['destination']
        return base

    def _channel_matches(self, channel_id: str, channel_name: str, config_id: str) -> bool:
        """Check if channel matches configuration."""
        # RSS: uses URL as ID
        if config_id.startswith('http'):
            return channel_id == config_id

        # Direct username/id matches
        if channel_id == config_id or channel_name == config_id:
            return True

        # Handle -100 prefix for supergroups
        if f"-100{channel_id}" == config_id:
            return True

        # Handle numeric IDs without -100 prefix
        if config_id.isdigit() and channel_id == f"-100{config_id}":
            return True

        return False
