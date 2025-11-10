"""
MessageRouter - Message routing and keyword matching

This module handles:
- Routing: Determining which destination(s) should receive a message
- Keyword Matching: Filtering messages based on configured keywords
- Parsing: Trimming lines from message text per destination
- Channel Matching: Flexible matching of channel IDs (username, numeric ID, RSS URL)
"""
from typing import List, Dict, Optional
from pathlib import Path
import mimetypes
from LoggerSetup import setup_logger
from ConfigManager import ConfigManager
from MessageData import MessageData
from AppTypes import APP_TYPE_DISCORD, APP_TYPE_TELEGRAM, APP_TYPE_RSS
from AllowedFileTypes import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES

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

    def is_channel_restricted(self, src_channel_id: str, src_channel_name: str, src_type: str) -> bool:
        """Check if any destination has restricted mode enabled for this channel.

        Restricted mode blocks certain media types (e.g., photos, videos, executables) to prevent
        forwarding of potentially unwanted content.

        Args:
            src_channel_id: Channel's unique identifier
            src_channel_name: Channel's display name
            src_type: Source type (APP_TYPE_RSS, APP_TYPE_TELEGRAM, etc.)

        Returns:
            bool: True if any destination monitoring this channel has restricted_mode=True
        """
        for destination in self.config.destinations:
            for dst_channel in destination['channels']:
                if self._channel_matches(src_channel_id, src_channel_name, src_type, dst_channel['id']):
                    if dst_channel.get('restricted_mode', False):
                        return True
        return False

    def is_ocr_enabled_for_channel(self, src_channel_id: str, src_channel_name: str, src_type: str) -> bool:
        """Check if any destination has OCR enabled for this channel.

        OCR (Optical Character Recognition) extracts text from images for
        keyword matching and message forwarding.

        Args:
            src_channel_id: Channel's unique identifier
            src_channel_name: Channel's display name
            src_type: Platform (RSS, Telegram, etc.)

        Returns:
            bool: True if any destination monitoring this channel has ocr=True
        """
        for destination in self.config.destinations:
            for dst_channel in destination['channels']:
                if self._channel_matches(src_channel_id, src_channel_name, src_type, dst_channel['id']):
                    if dst_channel.get('ocr', False):
                        return True
        return False

    def add_channel_mapping(self, config_id: str, actual_id: str) -> None:
        """Store mapping between configured ID and actual channel ID.

        Used to map user friendly config IDs to platform specific numeric IDs.

        Args:
            config_id: ID as specified in configuration
            actual_id: Actual platform ID resolved at runtime
        """
        self.channel_mappings[config_id] = actual_id

    def get_destinations(self, message_data: MessageData) -> List[Dict]:
        """Find all destinations that should receive this message based on keyword matching.

        1. Verify the source channel is configured (early exit if not)
        2. For each destination in config:
            a. Check if this destination monitors the source channel
            b. Build searchable text (message + OCR if enabled + attachment text if enabled)
            c. Match against keywords (or forward all if no keywords configured)
            d. Include destination in results if matched

        Keyword matching is case-insensitive. If OCR is enabled for a destination
        and OCR text is available, both message text and OCR text are searched.
        Similar is done with text-based attachments.

        Args:
            message_data: Message to route to destinations

        Returns:
            List[Dict]: List of destination entries that matched. Each dict contains
                routing metadata (name, type, keywords, parser, etc.)
        """
        destinations: List[Dict] = []

        # Check if this channel is configured anywhere
        channel_is_configured = False
        for destination in self.config.destinations:
            for dst_channel in destination.get('channels', []):
                if self._channel_matches(message_data.channel_id, message_data.channel_name, message_data.source_type, dst_channel['id']):
                    channel_is_configured = True
                    break
            if channel_is_configured:
                break

        # Early exit if channel is not monitored by any destination
        if not channel_is_configured:
            _logger.info(f"[MessageRouter] No configured matches for channel {message_data.channel_name} ({message_data.channel_id})")
            return destinations

        # Collect all matching destinations
        for destination in self.config.destinations:
            # Find the channel configuration for this destination (if it monitors this channel)
            dst_channel_config = None
            for dst_channel in destination['channels']:
                if self._channel_matches(message_data.channel_id, message_data.channel_name, message_data.source_type, dst_channel['id']):
                    dst_channel_config = dst_channel
                    break

            # Skip if this destination doesn't monitor this channel
            if not dst_channel_config:
                continue

            # Build searchable text: message text + OCR text (if OCR enabled and available)
            searchable_text = message_data.text or ""
            if dst_channel_config.get('ocr', False) and message_data.ocr_raw:
                # Combine message text and OCR text for keyword matching
                searchable_text = f"{searchable_text}\n{message_data.ocr_raw}" if searchable_text else message_data.ocr_raw

            # Check text-based attachments (enabled by default)
            if dst_channel_config.get('check_attachments', True) and message_data.media_path:
                attachment_text = self._extract_attachment_text(message_data.media_path)
                if attachment_text:
                    searchable_text = (
                        f"{searchable_text}\n{attachment_text}"
                        if searchable_text
                        else attachment_text
                    )

            # Perform case-insensitive keyword matching
            keywords = dst_channel_config.get('keywords')
            if not keywords:
                # No keywords configured, forward all messages from this channel
                destinations.append(self._make_dest_entry(destination, dst_channel_config, matched=[]))
            elif searchable_text:
                matched = [kw for kw in keywords if kw.lower() in searchable_text.lower()]
                if matched:
                    destinations.append(self._make_dest_entry(destination, dst_channel_config, matched=matched))

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

        # Check keep_first_lines (takes precedence if present)
        if 'keep_first_lines' in parser_config:
            keep = int(parser_config.get('keep_first_lines', 0) or 0)

            if keep <= 0:
                _logger.warning(f"[MessageRouter] Invalid keep_first_lines={keep}, must be > 0")
                return message_data

            lines = text.split('\n')
            kept_lines = lines[:keep]

            # Add to msg that lines were omitted
            if len(lines) > keep:
                omitted_count = len(lines) - keep
                new_text = '\n'.join(kept_lines) + f"\n\n**[{omitted_count} more line(s) omitted by parser]**"
            else:
                # Message has fewer lines than keep limit
                new_text = '\n'.join(kept_lines)

            return self._create_parsed_message(message_data, new_text)

        # trim_front_lines + trim_back_lines
        front = int(parser_config.get('trim_front_lines', 0) or 0)
        back = int(parser_config.get('trim_back_lines', 0) or 0)

        # Validate values
        if front < 0 or back < 0:
            _logger.warning(f"[MessageRouter] Invalid parser values: front={front}, back={back} must be nonnegative")
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
            trim_counts = " and ".join(parts)
            new_text = f"**[Message content removed by parser: {trim_counts} line(s) stripped]**"

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
        """Extract searchable text from attachments.

        Supports searchable text-based files. Reads entire file for complete keyword checking.
        Files must pass both extension and MIME type checks to be processed. This helps prevent
        potentially unwanted files from being read even if they have spoofed extensions.

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
            _logger.info(f"[MessageRouter] Skipping attachment with disallowed extension: {path.name}")
            return None

        # Check MIME type
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
            _logger.info(
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

        # Read entire file content
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

    def _make_dest_entry(self, destination: Dict, dst_channel_config: Dict, matched: List[str]) -> Dict:
        """Create normalized destination entry with routing metadata.

        Combines destination config and channel specific config into a single dict
        for use in message routing and dispatch.

        Args:
            destination: Destination configuration
            dst_channel_config: Destination channel specific configuration (keywords, parser, etc.)
            matched: List of keywords that matched for this message

        Returns:
            Dict: Normalized destination entry with all routing metadata
        """
        base = {
            'name': destination['name'],
            'type': destination['type'],
            'keywords': matched,
            'restricted_mode': dst_channel_config.get('restricted_mode', False),
            'parser': dst_channel_config.get('parser'),
            'ocr': dst_channel_config.get('ocr', False),
        }

        if base['type'] == APP_TYPE_DISCORD:
            base['discord_webhook_url'] = destination['discord_webhook_url']
        elif base['type'] == APP_TYPE_TELEGRAM:
            base['telegram_dst_channel'] = destination['telegram_dst_channel']
        
        return base

    def _channel_matches(self, src_channel_id: str, src_channel_name: str, src_type: str, dst_config_id: str) -> bool:
        """Check if the source channel matches one a destination is monitoring.

        Handles multiple source types and ID formats:
        - RSS feeds: Matched by exact URL comparison
        - Telegram usernames: @channelname
        - Telegram numeric IDs: -1001234567890 (with or without the -100 prefix)

        Args:
            src_channel_id: Actual channel identifier from message source
            src_channel_name: Source channel's display name
            src_type: Platform (RSS, Telegram, etc.)
            dst_config_id: ID specified in destination configuration

        Returns:
            bool: True if source channel matches the destination config ID
        """
        if src_type == APP_TYPE_RSS:
            return src_channel_id == dst_config_id

        if src_type == APP_TYPE_TELEGRAM:
            # Direct matches: username or exact ID
            if src_channel_id == dst_config_id or src_channel_name == dst_config_id:
                return True

            # Telegram supergroup: Config has -100 prefix, src_channel_id doesn't
            if f"-100{src_channel_id}" == dst_config_id:
                return True

            # Telegram supergroup: Config lacks -100 prefix, src_channel_id has it
            if dst_config_id.isdigit() and src_channel_id == f"-100{dst_config_id}":
                return True

        return False
