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
from pathlib import Path
import mimetypes
from logger_setup import setup_logger
from ConfigManager import ConfigManager
from MessageData import MessageData
from allowed_file_types import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES

_logger = setup_logger(__name__)


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
        for destination in self.config.destinations:
            for channel in destination['channels']:
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
        for destination in self.config.destinations:
            for channel in destination['channels']:
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
                - discord_webhook_url: (Discord only) Webhook URL
                - telegram_destination_channel: (Telegram only) Channel ID

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
        for destination in self.config.destinations:
            for channel in destination.get('channels', []):
                if self._channel_matches(message_data.channel_id, message_data.channel_name, channel['id']):
                    channel_is_configured = True
                    break
            if channel_is_configured:
                break

        if not channel_is_configured:
            _logger.info(f"[MessageRouter] No configured matches for channel {message_data.channel_name} ({message_data.channel_id})")
            return destinations

        # STEP 2: Collect all matching destinations
        for destination in self.config.destinations:
            # Find the channel configuration for this destination (if it monitors this channel)
            channel_config = None
            for channel in destination['channels']:
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

            # Check text-based attachments (enabled by default)
            if channel_config.get('check_attachments', True) and message_data.media_path:
                attachment_text = self._extract_attachment_text(message_data.media_path)
                if attachment_text:
                    searchable_text = (
                        f"{searchable_text}\n{attachment_text}"
                        if searchable_text
                        else attachment_text
                    )

            # Perform keyword matching
            keywords = channel_config.get('keywords')
            if not keywords:
                # No keywords configured - forward all messages from this channel
                destinations.append(self._make_dest_entry(destination, channel_config, matched=[]))
            elif searchable_text:
                # Case-insensitive keyword matching
                matched = [kw for kw in keywords if kw.lower() in searchable_text.lower()]
                if matched:
                    destinations.append(self._make_dest_entry(destination, channel_config, matched=matched))

        return destinations

    def parse_msg(self, message_data: MessageData, parser_config: Optional[Dict]) -> MessageData:
        """Apply text parsing rules to message.

        Parser supports (mutually exclusive):
        - keep_first_lines: Keep only first N lines, discard rest
        - trim_front_lines + trim_back_lines: Remove N lines from each end

        Args:
            message_data: Original message
            parser_config: Parser configuration dict

        Returns:
            New MessageData with modified text
        """
        text = message_data.text or ""
        if not text or not isinstance(parser_config, dict):
            return message_data

        # OPTION 1: keep_first_lines (takes precedence if present)
        if 'keep_first_lines' in parser_config:
            keep = int(parser_config.get('keep_first_lines', 0) or 0)

            if keep <= 0:
                _logger.warning(f"[MessageRouter] Invalid keep_first_lines={keep}, must be > 0")
                return message_data

            lines = text.split('\n')
            kept_lines = lines[:keep]

            # Add notice if lines were omitted
            if len(lines) > keep:
                omitted_count = len(lines) - keep
                new_text = '\n'.join(kept_lines) + f"\n\n**[{omitted_count} more line(s) omitted by parser]**"
            else:
                # Message has fewer lines than keep limit
                new_text = '\n'.join(kept_lines)

            return self._create_parsed_message(message_data, new_text)

        # OPTION 2: trim_front_lines + trim_back_lines
        front = int(parser_config.get('trim_front_lines', 0) or 0)
        back = int(parser_config.get('trim_back_lines', 0) or 0)

        # Validate values
        if front < 0 or back < 0:
            _logger.warning(f"[MessageRouter] Invalid parser values: front={front}, back={back} must be >= 0")
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
            hint = " and ".join(parts)
            new_text = f"**[Message content removed by parser: {hint} line(s) stripped]**"

        return self._create_parsed_message(message_data, new_text)

    def _create_parsed_message(self, original: MessageData, new_text: str) -> MessageData:
        """Create new MessageData with modified text, preserving all other fields.

        Args:
            original: Original MessageData
            new_text: Modified text content

        Returns:
            New MessageData instance with updated text
        """
        return MessageData(
            source_type=original.source_type,
            channel_id=original.channel_id,
            channel_name=original.channel_name,
            username=original.username,
            timestamp=original.timestamp,
            text=new_text,
            has_media=original.has_media,
            media_type=original.media_type,
            media_path=original.media_path,
            reply_context=original.reply_context,
            original_message=original.original_message,
            ocr_enabled=original.ocr_enabled,
            ocr_raw=original.ocr_raw,
            metadata=original.metadata
        )

    def _extract_attachment_text(self, media_path: Optional[str]) -> Optional[str]:
        """Extract searchable text from text-based attachment files.

        Supports safe, non-malicious text files (txt, log, csv, json, xml, yaml, md, sql,
        ini, conf, cfg, env, toml). Reads entire file for complete keyword checking
        (supports 3GB+ files).

        Security: Files must pass BOTH extension and MIME type checks to be processed.
        This prevents malicious files from being read even if they have spoofed extensions.

        Args:
            media_path: Path to downloaded media file

        Returns:
            Extracted text content (entire file), or None if:
            - Extension not in allowed list
            - MIME type not in allowed list
            - File doesn't exist
            - Read error occurred
        """
        if not media_path:
            return None

        path = Path(media_path)
        if not path.exists():
            return None

        # Check file extension
        file_extension = path.suffix.lower()
        if file_extension not in ALLOWED_EXTENSIONS:
            _logger.debug(f"[MessageRouter] Skipping attachment with disallowed extension: {path.name}")
            return None

        # Check MIME type
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
            _logger.debug(
                f"[MessageRouter] Skipping attachment with disallowed MIME type: "
                f"{path.name} (extension={file_extension}, mime={mime_type})"
            )
            return None

        # Log file size for large files
        file_size = path.stat().st_size
        if file_size > 100 * 1024 * 1024:  # Log if > 100MB
            _logger.info(
                f"[MessageRouter] Reading {file_size / (1024*1024):.1f}MB attachment for keyword checking: {path.name}"
            )

        # Read entire file content with encoding fallback
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            _logger.debug(
                f"[MessageRouter] Extracted {len(content)} chars from {path.name} "
                f"for keyword checking"
            )
            return content

        except Exception as e:
            _logger.warning(
                f"[MessageRouter] Failed to read attachment {path.name}: {e}"
            )
            return None

    def _make_dest_entry(self, destination: Dict, channel_config: Dict, matched: List[str]) -> Dict:
        """Create normalized destination entry with routing metadata.

        Combines destination config and channel-specific config into a single dict
        for use in message routing and dispatch.

        Args:
            destination: Destination configuration
            channel_config: Channel-specific configuration (keywords, parser, etc.)
            matched: List of keywords that matched for this message

        Returns:
            Dict: Normalized destination entry with all routing metadata
        """
        base = {
            'name': destination['name'],
            'type': destination['type'],
            'keywords': matched,
            'restricted_mode': channel_config.get('restricted_mode', False),
            'parser': channel_config.get('parser'),
            'ocr': channel_config.get('ocr', False),
        }
        if base['type'] == 'discord':
            base['discord_webhook_url'] = destination['discord_webhook_url']
        else:
            base['telegram_destination_channel'] = destination['telegram_destination_channel']
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
