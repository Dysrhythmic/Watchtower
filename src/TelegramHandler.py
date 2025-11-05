import logging
import os
from typing import Optional, Dict, List
from telethon import TelegramClient, events, utils
from telethon.errors import ChatAdminRequiredError, FloodWaitError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, Channel, User
from ConfigManager import ConfigManager
from MessageData import MessageData
from DestinationHandler import DestinationHandler

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramHandler(DestinationHandler):
    """Handles all Telegram operations."""

    # Telegram limits
    TELEGRAM_CAPTION_LIMIT = 1024  # Maximum caption length for media
    TELEGRAM_MESSAGE_LIMIT = 4096  # Maximum message length

    # Define allowed file types for restricted mode
    ALLOWED_MIME_TYPES = {
        "text/plain", "text/csv", "text/xml", "application/sql",
        "application/octet-stream", "application/x-sql", "application/x-msaccess",
        "application/json"
    }

    ALLOWED_EXTENSIONS = {
        '.txt', '.csv', '.log', '.sql', '.xml', '.dat', '.db', '.mdb', '.json'
    }

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        session_path = str(self.config.project_root / "config" / "watchtower_session.session")
        self.client = TelegramClient(session_path, config.api_id, config.api_hash)
        self.channels = {}  # channel_id -> entity mapping for Telegram API
        self.msg_callback = None
        self._msg_counter = 0

        # Destination resolution cache: spec (@name or -100id) -> int chat_id
        self._dest_cache: Dict[str, int] = {}

    async def start(self) -> None:
        """Start client and resolve channels."""
        await self.client.start()
        logger.info("[TelegramHandler] Telegram client started")

        # Resolve all channels
        for channel_id in self.config.get_all_channel_ids():
            telegram_entity = await self._resolve_channel(channel_id)
            if telegram_entity:
                entity_id = str(utils.get_peer_id(telegram_entity))
                self.channels[entity_id] = telegram_entity
                name = f"@{telegram_entity.username}" if getattr(telegram_entity, 'username', None) else telegram_entity.title
                self.config.channel_names[entity_id] = name
                logger.info(f"[TelegramHandler] Resolved {channel_id} -> ID: {entity_id}, Name: {name}")
            else:
                logger.error(f"[TelegramHandler] Failed to resolve channel: {channel_id}")

        logger.info(f"[TelegramHandler] Resolved {len(self.channels)} channels")

    async def _resolve_entity(self, identifier: str):
        """Shared entity resolution logic for channels and destinations.

        Handles @username, -100xxx numeric IDs, and bare usernames.
        """
        if identifier.startswith('@'):
            return await self.client.get_entity(identifier)
        elif identifier.startswith('-100'):
            return await self.client.get_entity(int(identifier))
        elif identifier.lstrip('-').isdigit():
            return await self.client.get_entity(int(identifier))
        else:
            return await self.client.get_entity(f"@{identifier}")

    async def _resolve_channel(self, channel_id: str):
        """Resolve a channel ID to a Telegram entity."""
        try:
            return await self._resolve_entity(channel_id)
        except Exception as e:
            logger.error(f"[TelegramHandler] Failed to resolve {channel_id}: {e}")
            return None

    async def fetch_latest_messages(self):
        """Fetch latest message from each channel for connection proof."""
        for channel_id, telegram_entity in self.channels.items():
            channel_name = self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}")
            try:
                async for message in self.client.iter_messages(telegram_entity, limit=1):
                    if message and self.msg_callback:
                        message_data = await self._create_message_data(message, channel_id)
                        await self.msg_callback(message_data, is_latest=True)
                    break
            except Exception as e:
                logger.error(f"[TelegramHandler] Error fetching from {channel_name}: {e}")

    def setup_handlers(self, callback) -> None:
        """Setup message event handlers."""
        self.msg_callback = callback

        configured_unique = len(self.config.get_all_channel_ids())
        resolved_count = len(self.channels)
        logger.info(f"[TelegramHandler] Channels in configuration: {configured_unique}")
        logger.info(f"[TelegramHandler] Channels successfully resolved: {resolved_count}")

        @self.client.on(events.NewMessage())
        async def handle_message(event):
            try:
                channel_id = str(event.chat_id)
                channel_name = self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}")
                message_data = await self._create_message_data(event.message, channel_id)
                telegram_msg_id = getattr(message_data.original_message, "id", None)
                logger.info(f"[TelegramHandler] Received message tg_id={telegram_msg_id} from {channel_name}")

                await callback(message_data, is_latest=False)

            except Exception as e:
                channel_name = self.config.channel_names.get(str(event.chat_id), f"Unresolved:{event.chat_id}")
                logger.error(f"[TelegramHandler] Error handling message from {channel_name}: {e}", exc_info=True)

    async def _create_message_data(self, message, channel_id: str) -> MessageData:
        """Create MessageData from Telegram message."""
        self._msg_counter += 1

        username = self._extract_username_from_sender(message.sender)
        media_type = self._get_media_type(message.media)

        # Get reply context if this is a reply
        reply_context = None
        if message.reply_to:
            reply_context = await self._get_reply_context(message)

        return MessageData(
            source_type="telegram",
            channel_id=channel_id,
            channel_name=self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}"),
            username=username,
            timestamp=message.date,
            text=message.text or "",
            has_media=bool(media_type),
            media_type=media_type,
            reply_context=reply_context,
            original_message=message
        )

    @staticmethod
    def _extract_username_from_sender(sender) -> str:
        """Extract display name from message sender."""
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
    def _get_media_type(media) -> Optional[str]:
        """Determine media type from Telegram message media."""
        if not media:
            return None

        if isinstance(media, MessageMediaPhoto):
            return "Photo"
        elif isinstance(media, MessageMediaDocument):
            return "Document"
        else:
            return "Other"

    async def _get_reply_context(self, message) -> Optional[Dict]:
        """Extract context about what message this is replying to."""
        try:
            replied_msg = await self.client.get_messages(
                message.chat_id,
                ids=message.reply_to.reply_to_msg_id
            )

            if replied_msg:
                author = self._extract_username_from_sender(replied_msg.sender)
                media_type = self._get_media_type(replied_msg.media)

                context = {
                    'message_id': replied_msg.id,
                    'author': author,
                    'text': replied_msg.text or "",
                    'time': replied_msg.date.strftime('%Y-%m-%d %H:%M:%S UTC') if replied_msg.date else "",
                    'media_type': media_type,
                    'has_media': bool(media_type)
                }
                return context

        except Exception as e:
            logger.error(f"[TelegramHandler] Error getting reply context: {e}", exc_info=True)

        return None

    def _is_media_restricted(self, message) -> bool:
        """Check if media is restricted under restricted mode rules.

        Args:
            message: The Telegram message object to check for restricted media.

        Returns:
            bool: True if media is RESTRICTED (blocked), False if media is allowed.

        Restricted mode is a security feature for CTI workflows that only allows
        specific document types (text files, logs, DBs) and blocks photos/videos.
        This prevents accidentally downloading and executing malicious media files.

        Both extension AND MIME type must match allowed lists for safety.
        """
        if not message.media:
            return False  # No media = not restricted

        if not isinstance(message.media, MessageMediaDocument):
            logger.info("[TelegramHandler] Media blocked by restricted mode: only documents are allowed in restricted mode")
            return True  # Non-document media = restricted

        document = message.media.document
        extension_allowed = False
        mime_allowed = False
        file_extension = None
        mime_type = getattr(document, "mime_type", None)

        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    file_extension = os.path.splitext(attr.file_name.lower())[1]
                    if file_extension in self.ALLOWED_EXTENSIONS:
                        extension_allowed = True
                        break

        if mime_type and mime_type in self.ALLOWED_MIME_TYPES:
            mime_allowed = True

        allowed = extension_allowed and mime_allowed
        if not allowed:
            logger.info(
                f"[TelegramHandler] Media blocked by restricted mode: "
                f"type={type(message.media).__name__}, ext={file_extension}, mime={mime_type}"
            )
        return not allowed  # Return True if restricted (not allowed), False if allowed

    async def download_media(self, message_data: MessageData) -> Optional[str]:
        """Download attached media from message into tmp/attachments/.

        Args:
            message_data: MessageData object containing the original Telegram message with media.

        Returns:
            Optional[str]: Path to the downloaded media file if successful, None otherwise.
        """
        try:
            if message_data.original_message and message_data.original_message.media:
                target_dir = str(self.config.attachments_dir) + os.sep
                return await message_data.original_message.download_media(file=target_dir)
        except Exception as e:
            logger.error(f"[TelegramHandler] Media download failed: {e}")
        return None

    @staticmethod
    def _defang_tme(url: str) -> str:
        """Defang t.me URLs to prevent accidental clicks in threat intelligence workflows.

        Replaces 'https://' with 'hxxps://' and '.' with '[.]' to make URLs non-clickable.
        This is a standard CTI practice to share potentially malicious content safely.
        """
        return (url
                .replace("https://t.me", "hxxps://t[.]me")
                .replace("http://t.me", "hxxp://t[.]me")
                .replace("https://telegram.me", "hxxps://telegram[.]me")
                .replace("http://telegram.me", "hxxp://telegram[.]me")
            )

    @staticmethod
    def build_message_url(channel_id: str, channel_username_or_name: str, message_id: Optional[int]) -> Optional[str]:
        """
        Build a canonical t.me link for a message, whether the chat is public or private.
        - Public:  https://t.me/<username>/<message_id>
        - Private: https://t.me/c/<internal_id>/<message_id>   (internal_id = chat_id with '-100' stripped)
        """
        if not message_id:
            return None

        # If we got a '@username' use the public form
        if channel_username_or_name and channel_username_or_name.startswith("@"):
            return f"https://t.me/{channel_username_or_name[1:]}/{message_id}"

        # Otherwise build the private/supergroup form using the numeric id
        # channel_id comes in as a string like '-1001234567890' or '1234567890'
        channel_id_str = channel_id
        if channel_id_str.startswith("-100"):
            internal = channel_id_str[4:]  # strip '-100'
        else:
            internal = channel_id_str.lstrip("-")
        return f"https://t.me/c/{internal}/{message_id}"

    @staticmethod
    def build_defanged_tg_url(channel_id: str, channel_username_or_name: str, message_id: Optional[int]) -> Optional[str]:
        """Build a defanged Telegram URL for threat intelligence workflows.

        Args:
            channel_id: Numeric channel ID (e.g., "-1001234567890").
            channel_username_or_name: Channel username (with/without @) or display name.
            message_id: Message ID number, or None.

        Returns:
            Optional[str]: Defanged URL (hxxps://t[.]me/...) if successful, None otherwise.
        """
        url = TelegramHandler.build_message_url(channel_id, channel_username_or_name, message_id)
        return TelegramHandler._defang_tme(url) if url else None


    # ---------- Telegram destination helpers ----------

    async def resolve_destination(self, channel_specifier: str) -> Optional[int]:
        """Resolve a destination '@username' or numeric id to chat_id (int).

        Uses caching to avoid repeated API calls for the same destination.
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
            logger.error(f"[TelegramHandler] Failed to resolve destination {channel_specifier}: {e}")
            return None

    def _get_rate_limit_key(self, destination_identifier) -> str:
        """Get rate limit key for Telegram (chat ID)."""
        return str(destination_identifier)

    def send_message(self, content: str, destination_chat_id: int, media_path: Optional[str] = None) -> bool:
        """Send message to Telegram destination (sync wrapper for async send_copy).

        This implements the DestinationHandler interface. Since Telegram operations
        are async, this is primarily for interface compatibility.

        Args:
            content: Message text to send
            destination_chat_id: Target channel/chat ID
            media_path: Optional path to media file

        Returns:
            bool: True if successful, False otherwise
        """
        import asyncio
        return asyncio.create_task(self.send_copy(destination_chat_id, content, media_path))

    async def send_copy(self, destination_chat_id: int, content: str, media_path: Optional[str]) -> bool:
        """Send formatted message to Telegram destination.

        Sends messages from any source (Telegram, RSS, etc.) as new messages
        with formatted content. Supports optional media attachment.

        Handles chunking internally based on Telegram's limits:
        - Captions: 1024 chars max
        - Messages: 4096 chars max

        Args:
            destination_chat_id: Target channel/chat ID
            content: Full message text (will be chunked internally if needed)
            media_path: Optional path to media file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Check and wait for rate limit
            self._check_and_wait_for_rate_limit(destination_chat_id)

            # Media with content
            if media_path and os.path.exists(media_path):
                if len(content) <= self.TELEGRAM_CAPTION_LIMIT:
                    # Content fits as caption - send media with caption
                    await self.client.send_file(destination_chat_id, media_path,
                                              caption=content or None, parse_mode='html')
                else:
                    # Content too long for caption - send media captionless, then chunk content at 4096
                    logger.info(f"[TelegramHandler] Content exceeds {self.TELEGRAM_CAPTION_LIMIT} chars, sending media captionless and text separately")
                    await self.client.send_file(destination_chat_id, media_path, caption=None)

                    # Chunk the FULL content at Telegram's message limit (4096 chars)
                    # This guarantees NO content is lost
                    chunks = self._chunk_text(content, self.TELEGRAM_MESSAGE_LIMIT)
                    for chunk in chunks:
                        await self.client.send_message(destination_chat_id, chunk, parse_mode='html')
                return True

            # Text only - chunk at 4096 if needed
            if len(content) <= self.TELEGRAM_MESSAGE_LIMIT:
                await self.client.send_message(destination_chat_id, content, parse_mode='html')
            else:
                chunks = self._chunk_text(content, self.TELEGRAM_MESSAGE_LIMIT)
                for chunk in chunks:
                    await self.client.send_message(destination_chat_id, chunk, parse_mode='html')
            return True

        except FloodWaitError as e:
            # Telegram rate limit - extract wait time and store
            self._store_rate_limit(destination_chat_id, e.seconds)
            return False

        except Exception as e:
            logger.error(f"[TelegramHandler] Copy send failed: {e}")
            return False

    def format_message(self, message_data: MessageData, destination: Dict) -> str:
        """Format message for Telegram using HTML markup.

        Args:
            message_data: MessageData object containing message content and metadata.
            destination: Destination configuration dictionary.

        Returns:
            str: Formatted message string using Telegram HTML markup.

        Mirrors Discord formatting but uses Telegram's HTML syntax:
        - Bold: <b>text</b>
        - Italic: <i>text</i>
        - Code: <code>text</code>
        - Blockquote: <blockquote>text</blockquote> (Telegram 5.13+)
        """
        from html import escape

        lines = [
            f"<b>New message from:</b> {escape(message_data.channel_name)}",
            f"<b>By:</b> {escape(message_data.username)}",
            f"<b>Time:</b> {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]

        # Add defanged source URL if available
        if 'src_url_defanged' in message_data.metadata:
            lines.append(f"<b>Source:</b> {escape(message_data.metadata['src_url_defanged'])}")

        if message_data.has_media:
            lines.append(f"<b>Content:</b> {escape(message_data.media_type)}")

        if destination.get('keywords'):
            keywords_formatted = ', '.join(f'<code>{escape(kw)}</code>' for kw in destination['keywords'])
            lines.append(f"<b>Matched:</b> {keywords_formatted}")

        if message_data.reply_context:
            lines.append(self._format_reply_context_html(message_data.reply_context))

        if message_data.text:
            lines.append(f"<b>Message:</b>\n{escape(message_data.text)}")

        # OCR raw text (if present) - formatted as blockquote for visual distinction
        if message_data.ocr_raw:
            ocr_escaped = escape(message_data.ocr_raw)
            # Use blockquote if supported, otherwise indent with spaces
            ocr_formatted = f"<blockquote>{ocr_escaped}</blockquote>"
            lines.append(f"<b>OCR:</b>\n{ocr_formatted}")

        return '\n'.join(lines)

    def _format_reply_context_html(self, reply_context: Dict) -> str:
        """Format reply context for Telegram display using HTML."""
        from html import escape

        parts = []
        author = escape(reply_context['author'])
        time = escape(reply_context['time'])
        parts.append(f"<b>  Replying to:</b> {author} ({time})")

        if reply_context.get('has_media'):
            media_type = escape(reply_context.get('media_type', 'Other'))
            parts.append(f"<b>  Original content:</b> {media_type}")

        original_text = reply_context.get('text', '')
        if original_text:
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"<b>  Original message:</b> {escape(original_text)}")
        elif reply_context.get('has_media'):
            parts.append("<b>  Original message:</b> [Media only, no caption]")

        return '\n'.join(parts)

    async def run(self) -> None:
        """Keep client running."""
        await self.client.run_until_disconnected()
