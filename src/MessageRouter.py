"""
MessageRouter - Intelligent message routing and keyword matching

This module handles routing of messages from sources (Telegram, RSS) to configured
destinations based on channel matching and keyword filtering. Provides message
parsing capabilities to trim unwanted content.

Key Concepts:
- Routing: Determining which destination(s) should receive a message
- Keyword Matching: Filtering messages based on configured keywords
- Parsing: Trimming lines from message text per destination
- Channel Matching: Flexible matching of channel IDs (username, numeric ID, RSS URL)

Routing Process:
    1. Check if message source channel is configured
    2. For each destination monitoring this channel:
        a. Build searchable text (message + OCR if enabled)
        b. Match against keywords (or forward all if no keywords)
        c. Add to results if matched

Telegram Channel ID Formats:
    - Username: @channelname
    - Numeric: -1001234567890 (supergroups have -100 prefix)
    - Config accepts with or without -100 prefix
"""
from typing import List, Dict, Optional
from logger_setup import setup_logger
from ConfigManager import ConfigManager
from MessageData import MessageData

logger = setup_logger(__name__)


class MessageRouter:
    """Routes messages to destinations based on channel and keyword configuration.

    Handles matching messages to destinations and applying per-destination
    configuration (OCR, restricted mode, parsers).
    """

    def __init__(self, config: ConfigManager):
        """Initialize router with configuration.

        Args:
            config: ConfigManager instance with destination configurations
        """
        self.config = config
        self.channel_mappings: Dict[str, str] = {}

    def is_channel_restricted(self, channel_id: str, channel_name: str) -> bool:
        """Check if any destination has restricted mode enabled for this channel.

        Restricted mode blocks certain media types (photos, videos) to prevent
        forwarding of potentially unwanted content.

        Args:
            channel_id: Channel's unique identifier
            channel_name: Channel's display name

        Returns:
            bool: True if any destination monitoring this channel has restricted_mode=True
        """
        for webhook in self.config.webhooks:
            for channel in webhook['channels']:
                if self._channel_matches(channel_id, channel_name, channel['id']):
                    if channel.get('restricted_mode', False):
                        return True
        return False

    def is_ocr_enabled_for_channel(self, channel_id: str, channel_name: str) -> bool:
        """Check if any destination has OCR enabled for this channel.

        OCR (Optical Character Recognition) extracts text from images for
        keyword matching and message forwarding.

        Args:
            channel_id: Channel's unique identifier
            channel_name: Channel's display name

        Returns:
            bool: True if any destination monitoring this channel has ocr=True
        """
        for webhook in self.config.webhooks:
            for channel in webhook['channels']:
                if self._channel_matches(channel_id, channel_name, channel['id']):
                    if channel.get('ocr', False):
                        return True
        return False

    def add_channel_mapping(self, config_id: str, actual_id: str) -> None:
        """Store mapping between configured ID and actual channel ID.

        Used to map user-friendly config IDs to platform-specific numeric IDs.

        Args:
            config_id: ID as specified in configuration
            actual_id: Actual platform ID resolved at runtime
        """
        self.channel_mappings[config_id] = actual_id

    def get_destinations(self, message_data: MessageData) -> List[Dict]:
        """Find all destinations that should receive this message based on keyword matching.

        Multi-step routing process:
        1. Verify the source channel is configured (early exit if not)
        2. For each destination in config:
            a. Check if this destination monitors the source channel
            b. Build searchable text (message text + OCR if enabled)
            c. Match against keywords (or forward all if no keywords configured)
            d. Include destination in results if matched

        Keyword matching is case-insensitive. If OCR is enabled for a destination
        and OCR text is available, both message text and OCR text are searched.

        Args:
            message_data: Message to route

        Returns:
            List[Dict]: Matched destination configs with the following keys:
                - name: Destination name
                - type: Platform type ('discord' or 'telegram')
                - keywords: List of matched keywords
                - restricted_mode: Whether restricted mode is enabled
                - parser: Parser configuration dict (or None)
                - ocr: Whether OCR is enabled
                - webhook_url: (Discord only) Webhook URL
                - destination: (Telegram only) Channel ID

        Example:
            >>> msg = MessageData(channel_id="@security", text="CVE-2024-1234 vulnerability")
            >>> dests = router.get_destinations(msg)
            >>> dests[0]['keywords']
            ['CVE']
        """
        destinations: List[Dict] = []

        # STEP 1: Check if this channel is configured anywhere
        # Early exit if channel is not monitored by any destination
        channel_is_configured = False
        for webhook in self.config.webhooks:
            for channel in webhook.get('channels', []):
                if self._channel_matches(message_data.channel_id, message_data.channel_name, channel['id']):
                    channel_is_configured = True
                    break
            if channel_is_configured:
                break

        if not channel_is_configured:
            logger.info(f"[MessageRouter] No configured matches for channel {message_data.channel_name} ({message_data.channel_id})")
            return destinations

        # STEP 2: Collect all matching destinations
        for webhook in self.config.webhooks:
            # Find the channel configuration for this destination (if it monitors this channel)
            channel_config = None
            for channel in webhook['channels']:
                if self._channel_matches(message_data.channel_id, message_data.channel_name, channel['id']):
                    channel_config = channel
                    break

            # Skip if this destination doesn't monitor this channel
            if not channel_config:
                continue

            # Build searchable text: message text + OCR text (if OCR enabled and available)
            searchable_text = message_data.text or ""
            if channel_config.get('ocr', False) and message_data.ocr_raw:
                # Combine message text and OCR text for keyword matching
                searchable_text = f"{searchable_text}\n{message_data.ocr_raw}" if searchable_text else message_data.ocr_raw

            # Perform keyword matching
            keywords = channel_config.get('keywords')
            if not keywords:
                # No keywords configured - forward all messages from this channel
                destinations.append(self._make_dest_entry(webhook, channel_config, matched=[]))
            elif searchable_text:
                # Case-insensitive keyword matching
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
        """Create normalized destination entry with routing metadata.

        Combines webhook config and channel-specific config into a single dict
        for use in message routing and dispatch.

        Args:
            webhook: Destination webhook configuration
            channel_config: Channel-specific configuration (keywords, parser, etc.)
            matched: List of keywords that matched for this message

        Returns:
            Dict: Normalized destination entry with all routing metadata
        """
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
        """Check if channel matches configuration ID.

        Handles multiple Telegram channel ID formats and RSS URL matching:
        - RSS feeds: Matched by URL (starts with http)
        - Telegram usernames: @channelname
        - Telegram numeric IDs: -1001234567890
        - Config flexibility: Accepts IDs with or without -100 prefix

        Telegram Supergroup ID Format:
            Telegram supergroups use numeric IDs with -100 prefix.
            Config can specify with or without prefix:
            - Config: "1234567890" matches actual ID "-1001234567890"
            - Config: "-1001234567890" matches actual ID "-1001234567890"

        Args:
            channel_id: Actual channel identifier from message source
            channel_name: Channel's display name
            config_id: ID specified in configuration

        Returns:
            bool: True if channel matches config ID

        Example:
            >>> router._channel_matches("-1001234567890", "MyChannel", "1234567890")
            True
            >>> router._channel_matches("@security", "Security News", "@security")
            True
            >>> router._channel_matches("feed123", "RSS Feed", "https://example.com/rss")
            False
        """
        # RSS feeds: Match by URL
        if config_id.startswith('http'):
            return channel_id == config_id

        # Direct matches: username or exact ID
        if channel_id == config_id or channel_name == config_id:
            return True

        # Telegram supergroup: Config has -100 prefix, channel_id doesn't
        if f"-100{channel_id}" == config_id:
            return True

        # Telegram supergroup: Config lacks -100 prefix, channel_id has it
        if config_id.isdigit() and channel_id == f"-100{config_id}":
            return True

        return False
