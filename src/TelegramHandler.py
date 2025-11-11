"""
TelegramHandler - Handles Telegram operations for both source and destination

This module handles all Telegram operations using the Telethon library

Key Features:
- Async message monitoring with automatic channel resolution
- Message downloading with media attachment support
- Restricted mode allows text-based files only
- URL defanging (https://t.me/... -> hxxps://t[.]me/...) for sources
- Rate limit handling with exponential backoff
- Reply context extraction for message threads
- HTML formatting for rich text display

Telegram API Details:
    - Caption limit: 1024 characters (for media captions)
    - Message limit: 4096 characters (for text messages)
    - Automatic chunking when content exceeds limits
    - Rate limiting via FloodWaitError with retry_after seconds
"""
import asyncio
import os
import time
from html import escape
from typing import Optional, Dict
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, Channel, User,
    DocumentAttributeVideo, DocumentAttributeAudio
)
from ConfigManager import ConfigManager
from MessageData import MessageData
from DestinationHandler import DestinationHandler
from LoggerSetup import setup_logger
from AllowedFileTypes import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES
from AppTypes import APP_TYPE_TELEGRAM

_logger = setup_logger(__name__)

class TelegramHandler(DestinationHandler):
    """Telegram handler for message monitoring and delivery.

    Attributes:
        MAX_CAPTION_LENGTH: Max caption length (1024 chars)
        MAX_MSG_LENGTH: Max message length (4096 chars)
        client: Telethon TelegramClient instance
        channels: Resolved channel entities (channel_id -> entity)
        msg_callback: Callback function for new messages
    """

    MAX_CAPTION_LENGTH = 1024 
    MAX_MSG_LENGTH = 4096
    _FILE_SIZE_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB

    _DEFAULT_POLL_INTERVAL = 300  # seconds

    def __init__(self, config: ConfigManager, metrics=None):
        """Initialize TelegramHandler with configuration.

        Creates Telethon client with session file and API credentials from config.
        Session file stores authentication state to avoid re-login on restarts.

        Args:
            config: ConfigManager with api_id, api_hash, and channel configurations
            metrics: Optional MetricsCollector instance for tracking statistics
        """
        super().__init__()
        self.config = config
        self._metrics = metrics
        session_path = str(config.config_dir / "watchtower_session.session")
        self.client = TelegramClient(session_path, config.api_id, config.api_hash)
        self.channels = {}  # channel_id -> entity mapping for Telegram API
        self.msg_callback = None
        self._msg_counter = 0

        # Destination resolution cache: spec (@name or -100id) -> int chat_id
        self._dest_cache: Dict[str, int] = {}

    @property
    def file_size_limit(self) -> int:
        """Maximum file size in bytes for Telegram."""
        return self._FILE_SIZE_LIMIT

    async def start(self) -> None:
        """Start Telegram client and resolve all configured channels.

        Connects to Telegram, authenticates using session file, and resolves all
        channel IDs from config into Telegram entities. Stores resolved entities
        in self.channels for message monitoring. Logs success/failure for each channel.
        """
        await self.client.start()
        _logger.info("Telegram client started")

        for channel_id in self.config.get_all_channel_ids():
            try:
                telegram_entity = await self._resolve_entity(channel_id)
                entity_id = str(utils.get_peer_id(telegram_entity))
                self.channels[entity_id] = telegram_entity
                name = f"@{telegram_entity.username}" if getattr(telegram_entity, 'username', None) else telegram_entity.title
                self.config.channel_names[entity_id] = name
                _logger.info(f"Resolved {channel_id} -> ID: {entity_id}, Name: {name}")
            except Exception as e:
                _logger.error(f"Failed to resolve {channel_id}: {e}")

        _logger.info(f"Resolved {len(self.channels)} channels")

    async def _resolve_entity(self, identifier: str):
        """Shared entity resolution logic for channels and destinations.

        Handles multiple Telegram identifier formats:
        - @username: Direct username lookup
        - -100xxx: Supergroup numeric ID
        - xxx: Bare numeric ID
        - username: Bare username (adds @ prefix automatically)

        Args:
            identifier: Channel identifier in any supported format

        Returns:
            Telegram entity (Channel, User, or Chat object)

        Raises:
            Exception: If entity cannot be resolved
        """
        if identifier.startswith('@'):
            return await self.client.get_entity(identifier)
        elif identifier.startswith('-100'):
            return await self.client.get_entity(int(identifier))
        elif identifier.lstrip('-').isdigit():
            return await self.client.get_entity(int(identifier))
        else:
            return await self.client.get_entity(f"@{identifier}")

    def _get_channel_name(self, channel_id: str) -> str:
        """Get friendly channel name, or 'Unresolved:ID' if unknown.

        Args:
            channel_id: Channel ID (username, numeric ID, or identifier)

        Returns:
            str: Human-readable channel name or "Unresolved:{channel_id}"

        Examples:
            >>> handler._get_channel_name("@test_channel")
            "Test Channel"  # If in channel_names
            >>> handler._get_channel_name("-100123456789")
            "Unresolved:-100123456789"  # If not resolved yet
        """
        return self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}")

    def _telegram_log_path(self, channel_id: str):
        """Get path to telegram log file for a channel.

        Converts channel ID to a safe filename by stripping prefixes:
        - Removes -100 prefix from numeric IDs (supergroup format)
        - Removes @ prefix from username IDs

        Args:
            channel_id: Channel ID (e.g., '-100123456789', '@channelname', '123456789')

        Returns:
            Path: Path object to the log file

        Examples:
            >>> handler._telegram_log_path('-100123456789')
            Path('/tmp/telegramlog/123456789.txt')
            >>> handler._telegram_log_path('@channelname')
            Path('/tmp/telegramlog/channelname.txt')
            >>> handler._telegram_log_path('123456789')
            Path('/tmp/telegramlog/123456789.txt')
        """
        # Use removeprefix (Python 3.9+) to properly strip prefixes
        clean_id = channel_id.removeprefix('-100').removeprefix('@')
        return self.config.telegramlog_dir / f"{clean_id}.txt"

    def _create_telegram_log(self, channel_id: str, msg_id: int) -> None:
        """Create telegram log file with channel name and message ID.

        Creates a two-line text file:
        Line 1: Human-readable channel name (for manual inspection)
        Line 2: Last processed message ID (integer)

        Called during connection proof to initialize tracking for each channel.

        Args:
            channel_id: Channel ID from config
            msg_id: Message ID to record as last processed

        Returns:
            None

        Example file content:
            My Channel Name
            12345
        """
        log_path = self._telegram_log_path(channel_id)
        channel_name = self._get_channel_name(channel_id)

        content = f"{channel_name}\n{msg_id}\n"
        log_path.write_text(content, encoding='utf-8')
        _logger.info(f"Created log for {channel_name}: msg_id={msg_id}")

    def _read_telegram_log(self, channel_id: str) -> Optional[int]:
        """Read last processed message ID from telegram log.

        Reads the message ID from line 2 of the log file. Returns None if
        the log doesn't exist or is corrupted.

        Args:
            channel_id: Channel ID to read log for

        Returns:
            Optional[int]: Last processed message ID, or None if log doesn't exist
                          or cannot be parsed

        Examples:
            >>> handler._read_telegram_log('-100123456789')
            12345
            >>> handler._read_telegram_log('new_channel')
            None
        """
        log_path = self._telegram_log_path(channel_id)
        if not log_path.exists():
            return None

        try:
            lines = log_path.read_text(encoding='utf-8').strip().split('\n')
            if len(lines) >= 2:
                return int(lines[1])
        except Exception as e:
            _logger.error(f"Error reading log for {channel_id}: {e}")
        return None

    def _update_telegram_log(self, channel_id: str, msg_id: int) -> None:
        """Update telegram log with new message ID.

        Overwrites the log file with updated message ID while preserving
        the channel name on line 1.

        Called after processing each message to track progress and prevent
        duplicate processing on restart.

        Args:
            channel_id: Channel ID to update log for
            msg_id: New message ID to record

        Returns:
            None
        """
        log_path = self._telegram_log_path(channel_id)
        channel_name = self._get_channel_name(channel_id)

        content = f"{channel_name}\n{msg_id}\n"
        log_path.write_text(content, encoding='utf-8')
        _logger.debug(f"Updated log for {channel_name}: msg_id={msg_id}")

    async def fetch_latest_messages(self):
        """Fetch latest message from each channel for connection proof.

        Retrieves the most recent message from each monitored channel and passes
        it to the message callback with is_latest=True flag. Used during startup
        to verify channel connectivity and permissions.

        Also creates Telegram log files with the latest message ID for each channel,
        enabling missed message detection during polling.
        """
        for channel_id, telegram_entity in self.channels.items():
            channel_name = self._get_channel_name(channel_id)
            try:
                async for message in self.client.iter_messages(telegram_entity, limit=1):
                    if message:
                        self._create_telegram_log(channel_id, message.id)

                        if self.msg_callback:
                            message_data = await self._create_message_data(message, channel_id)
                            await self.msg_callback(message_data, is_latest=True)
                    break
            except Exception as e:
                _logger.error(f"Error fetching from {channel_name}: {e}")

    async def poll_missed_messages(self):
        """Poll for messages that may have been missed during downtime.

        Checks all connected channels for messages with IDs greater than the last
        processed ID stored in Telegram logs. Processes any missed messages and
        updates the logs accordingly.

        This runs continuously in a loop with DEFAULT_POLL_INTERVAL delay between
        iterations. Should be run as a background task.
        """
        while True:
            try:
                await asyncio.sleep(self._DEFAULT_POLL_INTERVAL)

                for channel_id, telegram_entity in self.channels.items():
                    channel_name = self._get_channel_name(channel_id)
                    last_processed_id = self._read_telegram_log(channel_id)

                    if not last_processed_id:
                        continue

                    try:
                        # Fetch recent messages to check for any newer than last_processed_id
                        newest_msg_id = None
                        messages_to_process = []

                        # iter_messages() returns in reverse chronological order (newest first)
                        async for message in self.client.iter_messages(
                            telegram_entity,
                            limit=100  # Check last 100 messages for misses
                        ):
                            # First message is always the newest (highest ID)
                            if newest_msg_id is None:
                                newest_msg_id = message.id
                                # Check if we're up-to-date
                                if last_processed_id >= newest_msg_id:
                                    # No missed messages
                                    break
                                # Missed messages, log detection
                                _logger.warning(
                                    f"Detected missed messages in {channel_name}: "
                                    f"log_id={last_processed_id}, newest_id={newest_msg_id}"
                                )

                            # Check if we've reached messages we've already processed
                            if message.id <= last_processed_id:
                                break

                            # This is a missed message, collect it for processing
                            messages_to_process.append(message)

                        # Process all missed messages in chronological order (oldest first)
                        missed_count = 0
                        if messages_to_process:
                            messages_to_process.reverse()

                            for message in messages_to_process:
                                _logger.warning(
                                    f"Processing missed message: "
                                    f"{channel_name} msg_id={message.id}"
                                )

                                if self.msg_callback:
                                    message_data = await self._create_message_data(message, channel_id)
                                    await self.msg_callback(message_data, is_latest=False)

                            # Update log with the newest message ID
                            self._update_telegram_log(channel_id, newest_msg_id)

                            missed_count = len(messages_to_process)
                            if self._metrics:
                                self._metrics.increment("telegram_missed_msgs_caught", missed_count)
                            _logger.warning(
                                f"Processed {missed_count} missed messages "
                                f"from {channel_name} (newest_id={newest_msg_id})"
                            )

                        _logger.info(f"{channel_name} polled; missed={missed_count}")

                    except Exception as e:
                        _logger.error(f"Error polling {channel_name}: {e}")

            except Exception as e:
                _logger.error(f"Error in poll loop: {e}", exc_info=True)

    def setup_handlers(self, callback) -> None:
        """Setup message event handlers for monitoring new messages.

        Registers a global event handler for NewMessage events in Telegram.
        Each new message is converted to MessageData and passed to the callback function.

        Args:
            callback: Async function to call for each new message (message_data, is_latest)
        """
        self.msg_callback = callback

        configured_unique = len(self.config.get_all_channel_ids())
        _logger.info(f"Channels in configuration: {configured_unique}")
        resolved_count = len(self.channels)
        _logger.info(f"Channels successfully resolved: {resolved_count}")

        @self.client.on(events.NewMessage())
        async def handle_message(event):
            try:
                channel_id = str(event.chat_id)
                channel_name = self._get_channel_name(channel_id)
                telegram_msg_id = event.message.id

                # Update telegram log before creating message_data to prevent race condition with polling
                if telegram_msg_id:
                    self._update_telegram_log(channel_id, telegram_msg_id)

                _logger.debug(f"Received message tg_id={telegram_msg_id} from {channel_name}")

                # Create message_data and route
                message_data = await self._create_message_data(event.message, channel_id)
                await callback(message_data, is_latest=False)

            except Exception as e:
                channel_name = self._get_channel_name(str(event.chat_id))
                _logger.error(f"Error handling message from {channel_name}: {e}", exc_info=True)

    async def _create_message_data(self, message, channel_id: str) -> MessageData:
        """Create MessageData from Telegram message.

        Extracts all relevant information from Telegram message and converts
        to standardized MessageData format for routing and processing.

        Args:
            message: Telethon Message object
            channel_id: Source channel numeric ID

        Returns:
            MessageData: Standardized message container
        """
        self._msg_counter += 1

        username = self._extract_username_from_sender(message.sender)
        attachment_type = self._get_attachment_type(message.media)

        reply_context = None
        if message.reply_to:
            reply_context = await self._get_reply_context(message)

        return MessageData(
            source_type=APP_TYPE_TELEGRAM,
            channel_id=channel_id,
            channel_name=self._get_channel_name(channel_id),
            username=username,
            timestamp=message.date,
            text=message.text or "",
            has_attachments=bool(attachment_type),
            attachment_type=attachment_type,
            reply_context=reply_context,
            original_message=message
        )

    @staticmethod
    def _extract_username_from_sender(sender) -> str:
        """Extract display name from message sender.

        Handles different sender types (User, Channel) and falls back
        when username or name information is missing.

        Args:
            sender: Telegram sender object (User, Channel, or None)

        Returns:
            str: Display name (username, full name, or "Unknown")
        """
        if not sender:
            return "Unknown"

        if isinstance(sender, User):
            if sender.username:
                return f"@{sender.username}"
            elif sender.first_name:
                username = sender.first_name
                if sender.last_name:
                    username += f" {sender.last_name}"
                return username
        elif isinstance(sender, Channel):
            return f"@{sender.username}" if sender.username else "Channel"

        return f"@{getattr(sender, 'username', 'Unknown')}"

    @staticmethod
    def _get_attachment_type(media) -> Optional[str]:
        """Determine attachment type from Telegram message media object.

        Args:
            media: Telegram media object (MessageMediaPhoto, MessageMediaDocument, etc.)

        Returns:
            Optional[str]: "Photo", "Video", "Audio", "Document", or None if no media
        """
        if not media:
            return None

        if isinstance(media, MessageMediaPhoto):
            return "Photo"
        elif isinstance(media, MessageMediaDocument):
            # Check document attributes to determine specific type
            doc = media.document
            if not doc or not hasattr(doc, 'attributes'):
                return "Document"

            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeVideo):
                    return "Video"
                elif isinstance(attr, DocumentAttributeAudio):
                    return "Audio"

            # If no specific attributes found, it's a generic document/file
            return "Document"
        else:
            return "Other"

    async def _get_reply_context(self, message) -> Optional[Dict]:
        """Extract context about the message this is replying to.

        Fetches the original message being replied to and extracts relevant
        metadata for display in forwarded messages.

        Args:
            message: Telegram message object with reply_to field

        Returns:
            Optional[Dict]: Reply context with keys: message_id, author, text, time,
                          attachment_type, has_attachments. None if reply fetch fails.
        """
        try:
            replied_msg = await self.client.get_messages(
                message.chat_id,
                ids=message.reply_to.reply_to_msg_id
            )

            if replied_msg:
                author = self._extract_username_from_sender(replied_msg.sender)
                attachment_type = self._get_attachment_type(replied_msg.media)

                context = {
                    'message_id': replied_msg.id,
                    'author': author,
                    'text': replied_msg.text or "",
                    'time': replied_msg.date.strftime('%Y-%m-%d %H:%M:%S UTC') if replied_msg.date else "",
                    'attachment_type': attachment_type,
                    'has_attachments': bool(attachment_type)
                }
                return context

        except Exception as e:
            _logger.error(f"Error getting reply context: {e}", exc_info=True)

        return None

    def _is_attachment_restricted(self, message) -> bool:
        """Check if attachment is restricted under restricted mode rules.

        Args:
            message: The Telegram message object to check for restricted attachment.

        Returns:
            bool: True if attachment is restricted, False if attachment is allowed.

        Restricted mode is a security feature for CTI workflows that only allows
        specific document types (text files, logs, configs, etc.) to prevent
        accidentally downloading malicious or otherwise unwanted attachment files.

        Both extension and MIME type must match allowed lists for safety.
        """
        # No media -> not restricted
        if not message.media:
            return False 

        # Non-document attachment -> restricted
        if not isinstance(message.media, MessageMediaDocument):
            _logger.info("Attachment blocked by restricted mode: only documents are allowed in restricted mode")
            return True 

        document = message.media.document
        extension_allowed = False
        mime_allowed = False
        file_extension = None
        mime_type = getattr(document, "mime_type", None)

        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    file_extension = os.path.splitext(attr.file_name.lower())[1]
                    if file_extension in ALLOWED_EXTENSIONS:
                        extension_allowed = True
                        break

        if mime_type and mime_type in ALLOWED_MIME_TYPES:
            mime_allowed = True

        allowed = extension_allowed and mime_allowed
        if not allowed:
            _logger.info(
                f"Attachment blocked by restricted mode: "
                f"type={type(message.media).__name__}, ext={file_extension}, mime={mime_type}"
            )
        
        # Return True if restricted (not allowed), False if allowed
        return not allowed
    
    async def download_attachment(self, message_data: MessageData) -> Optional[str]:
        """Download attached file from message.

        Args:
            message_data: MessageData object containing the original Telegram message with attachment.

        Returns:
            Optional[str]: Path to the downloaded attachment file if successful, None otherwise.
        """
        try:
            if message_data.original_message and message_data.original_message.media:
                target_dir = str(self.config.attachments_dir) + os.sep
                attachment_path = await message_data.original_message.download_media(file=target_dir)
                if attachment_path:
                    file_size = os.path.getsize(attachment_path)
                    file_size_mb = file_size / (1024 * 1024)
                    _logger.info(
                        f"Attachment downloaded successfully: "
                        f"{os.path.basename(attachment_path)} ({file_size_mb:.2f} MB)"
                    )
                return attachment_path
        except Exception as e:
            _logger.error(f"Attachment download failed: {e}")
        return None

    @staticmethod
    def _defang_tme(url: str) -> str:
        """Defang t.me URLs to prevent accidental clicks when sharing potentially malicious content.

        Replaces 'http' with 'hxxp' and 't.me' with 't[.]me' to make URLs unclickable.
        """
        return (url
                .replace("https://t.me", "hxxps://t[.]me")
                .replace("http://t.me", "hxxp://t[.]me")
                .replace("https://telegram.me", "hxxps://telegram[.]me")
                .replace("http://telegram.me", "hxxp://telegram[.]me")
                .replace("HTTPS://T.ME", "hxxps://t[.]me")
                .replace("HTTP://T.ME", "hxxp://t[.]me")
            )

    @staticmethod
    def build_message_url(channel_id: str, channel_username_or_name: str, message_id: Optional[int]) -> Optional[str]:
        """Build a canonical t.me link for a message, whether public or private.

        Args:
            channel_id: Numeric channel ID (e.g., "-1001234567890")
            channel_username_or_name: Channel username (with/without @) or display name
            message_id: Message ID number

        Returns:
            Optional[str]: Telegram URL in format:
                - Public: https://t.me/<username>/<message_id>
                - Private: https://t.me/c/<internal_id>/<message_id>
                  (internal_id = chat_id with '-100' prefix stripped)
        """
        if not message_id:
            return None

        if channel_username_or_name and channel_username_or_name.startswith("@"):
            username = channel_username_or_name.removeprefix("@")
            return f"https://t.me/{username}/{message_id}"

        internal = channel_id.removeprefix("-100").removeprefix("-")
        return f"https://t.me/c/{internal}/{message_id}"

    @staticmethod
    def build_defanged_tg_url(channel_id: str, channel_username_or_name: str, message_id: Optional[int]) -> Optional[str]:
        """Build a defanged Telegram URL.

        Args:
            channel_id: Numeric channel ID (e.g., "-1001234567890").
            channel_username_or_name: Channel username (with/without @) or display name.
            message_id: Message ID number, or None.

        Returns:
            Optional[str]: Defanged URL (hxxps://t[.]me/...) if successful, None otherwise.
        """
        url = TelegramHandler.build_message_url(channel_id, channel_username_or_name, message_id)
        return TelegramHandler._defang_tme(url) if url else None

    async def resolve_destination(self, channel_specifier: str) -> Optional[int]:
        """Resolve a destination '@username' or numeric id to chat_id (int).

        Uses caching to avoid repeated API calls for the same destination.
        Handles both username and numeric ID formats.

        Args:
            channel_specifier: Destination identifier (@username or numeric ID)

        Returns:
            Optional[int]: Numeric chat_id if successful, None if resolution fails
        """
        if channel_specifier in self._dest_cache:
            return self._dest_cache[channel_specifier]

        try:
            if channel_specifier.lstrip('-').isdigit():
                chat_id = int(channel_specifier)
            else:
                telegram_entity = await self._resolve_entity(channel_specifier)
                chat_id = utils.get_peer_id(telegram_entity)

            self._dest_cache[channel_specifier] = chat_id
            return chat_id
        except Exception as e:
            _logger.error(f"Failed to resolve destination {channel_specifier}: {e}")
            return None

    def _extract_retry_after(self, error: Exception) -> Optional[float]:
        """Extract retry_after value from Telegram FloodWaitError.

        Args:
            error: FloodWaitError exception from Telegram API

        Returns:
            Optional[float]: Retry after seconds if error is FloodWaitError, None otherwise
        """
        if isinstance(error, FloodWaitError):
            return float(error.seconds)
        return None

    async def send_message(self, content: str, destination_chat_id: int, attachment_path: Optional[str] = None) -> bool:
        """Send formatted message to Telegram destination.

        Sends messages from any source (Telegram, RSS, etc.) as new messages
        with formatted content. Supports optional attachment file.

        Handles chunking internally based on Telegram's limits:
        - Captions: 1024 chars max
        - Messages: 4096 chars max

        Args:
            destination_chat_id: Target channel/chat ID
            content: Full message text (will be chunked internally if needed)
            attachment_path: Optional path to attachment file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check if rate limited and skip immediately if so
            if self.is_rate_limited(destination_chat_id):
                wait_until = self._rate_limits[destination_chat_id]
                wait_time = wait_until - time.time()
                _logger.info(f"[TelegramHandler] Destination {destination_chat_id} is rate limited for {wait_time:.1f}s more, skipping send")
                return False

            # Attachment with content
            if attachment_path and os.path.exists(attachment_path):
                if len(content) <= self.MAX_CAPTION_LENGTH:
                    # Content fits as caption, send attachment with caption
                    await self.client.send_file(destination_chat_id, attachment_path,
                                              caption=content or None, parse_mode='html')
                else:
                    # Content too long for caption, send attachment captionless then chunk content at 4096
                    _logger.info(f"Content exceeds {self.MAX_CAPTION_LENGTH} chars, sending attachment captionless and text separately")
                    await self.client.send_file(destination_chat_id, attachment_path, caption=None)

                    chunks = self._chunk_text(content, self.MAX_MSG_LENGTH)
                    for chunk in chunks:
                        await self.client.send_message(destination_chat_id, chunk, parse_mode='html')
                return True

            # Text only, chunk at 4096 if needed
            if len(content) <= self.MAX_MSG_LENGTH:
                await self.client.send_message(destination_chat_id, content, parse_mode='html')
            else:
                chunks = self._chunk_text(content, self.MAX_MSG_LENGTH)
                for chunk in chunks:
                    await self.client.send_message(destination_chat_id, chunk, parse_mode='html')
            return True

        except FloodWaitError as e:
            retry_after = self._extract_retry_after(e)
            if retry_after is not None:
                self._store_rate_limit(destination_chat_id, retry_after)
            return False

        except Exception as e:
            _logger.error(f"Copy send failed: {e}")
            return False

    def format_message(self, message_data: MessageData, destination: Dict) -> str:
        """Format message for Telegram using HTML markup.

        Args:
            message_data: MessageData object containing message content and metadata.
            destination: Destination configuration dictionary.

        Returns:
            str: Formatted message string using Telegram HTML markup.
        """
        lines = [
            f"<b>New message from:</b> {escape(message_data.channel_name)}",
            f"<b>By:</b> {escape(message_data.username)}",
            f"<b>Time:</b> {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]

        if 'src_url_defanged' in message_data.metadata:
            lines.append(f"<b>Source:</b> {escape(message_data.metadata['src_url_defanged'])}")

        if message_data.has_attachments:
            lines.append(f"<b>Content:</b> {escape(message_data.attachment_type)}")

        if destination.get('keywords'):
            keywords_formatted = ', '.join(f'<code>{escape(kw)}</code>' for kw in destination['keywords'])
            lines.append(f"<b>Matched:</b> {keywords_formatted}")

        if message_data.reply_context:
            lines.append(self._format_reply_context_html(message_data.reply_context))

        if message_data.text:
            lines.append(f"<b>Message:</b>\n{escape(message_data.text)}")

        if message_data.ocr_raw:
            ocr_escaped = escape(message_data.ocr_raw)
            ocr_formatted = f"<blockquote>{ocr_escaped}</blockquote>"
            lines.append(f"<b>OCR:</b>\n{ocr_formatted}")

        return '\n'.join(lines)

    def _format_reply_context_html(self, reply_context: Dict) -> str:
        """Format reply context for Telegram display using HTML.

        Args:
            reply_context: Reply metadata dict with author, time, text, attachment_type

        Returns:
            str: Formatted reply context with HTML markup
        """
        parts = []
        author = escape(reply_context['author'])
        time = escape(reply_context['time'])
        parts.append(f"<b>  Replying to:</b> {author} ({time})")

        if reply_context.get('has_attachments'):
            attachment_type = escape(reply_context.get('attachment_type', 'Other'))
            parts.append(f"<b>  Original content:</b> {attachment_type}")

        original_text = reply_context.get('text', '')
        if original_text:
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"<b>  Original message:</b> {escape(original_text)}")
        elif reply_context.get('has_attachments'):
            parts.append("<b>  Original message:</b> [Attachment only, no caption]")

        return '\n'.join(parts)

    async def run(self) -> None:
        """Keep Telegram client running indefinitely.

        Blocks until client disconnects. Used to maintain persistent connection
        for message monitoring. Should be run as async task.
        """
        await self.client.run_until_disconnected()
