import logging
import os
from typing import Optional, Dict
from telethon import TelegramClient, events, utils
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, Channel, User
from ConfigManager import ConfigManager
from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramHandler:
    """Handles all Telegram operations."""
    
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
        self.config = config
        session_path = str(self.config.project_root / "config" / "watchtower_session.session")
        self.client = TelegramClient(session_path, config.api_id, config.api_hash)
        self.channels = {}  # channel_id -> entity mapping for Telegram API
        self.msg_callback = None
        self._msg_counter = 0

    async def start(self):
        """Start client and resolve channels."""
        await self.client.start()
        logger.info("[TelegramHandler] Telegram client started")
        
        # Resolve all channels
        for channel_id in self.config.get_all_channel_ids():
            entity = await self._resolve_channel(channel_id)
            if entity:
                # Use telethon utils to get the correct peer ID to ensure it's the same ID format that events use
                entity_id = str(utils.get_peer_id(entity))
                
                self.channels[entity_id] = entity
                
                # Store friendly name
                name = f"@{entity.username}" if getattr(entity, 'username', None) else entity.title
                self.config.channel_names[entity_id] = name
                
                logger.info(f"[TelegramHandler] Resolved {channel_id} -> ID: {entity_id}, Name: {name}")
            else:
                logger.warning(f"[TelegramHandler] Failed to resolve channel: {channel_id}")
        
        logger.info(f"[TelegramHandler] Resolved {len(self.channels)} channels")
    
    async def _resolve_channel(self, channel_id: str):
        """Resolve a channel ID to an entity."""
        try:
            # Try different formats
            if channel_id.startswith('@'):
                return await self.client.get_entity(channel_id)
            elif channel_id.startswith('-100'):
                return await self.client.get_entity(int(channel_id))
            # Try with and without adding -100 prefix
            elif channel_id.isdigit():
                try:
                    return await self.client.get_entity(int(channel_id))
                except:
                    return await self.client.get_entity(int(f"-100{channel_id}"))
            else:
                # Try as username
                return await self.client.get_entity(f"@{channel_id}")
        except Exception as e:
            logger.error(f"[TelegramHandler] Failed to resolve {channel_id}: {e}")
            return None

    async def fetch_latest_messages(self):
        """Fetch latest message from each channel for connection proof."""
        for channel_id, entity in self.channels.items():
            channel_name = self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}")
            try:
                async for message in self.client.iter_messages(entity, limit=1):
                    if message and self.msg_callback:
                        msg_data = await self._create_message_data(message, channel_id)
                        await self.msg_callback(msg_data, is_latest=True)
                    break
            except Exception as e:
                logger.error(f"[TelegramHandler] Error fetching from {channel_name}: {e}")
    
    def setup_handlers(self, callback):
        """Setup message event handlers."""
        self.msg_callback = callback

        configured_unique = len(self.config.get_all_channel_ids())
        resolved_count = len(self.channels)
        logger.info(f"[TelegramHandler] Channels in configuration: {configured_unique}")
        logger.info(f"[TelegramHandler] Channels successfully resolved: {resolved_count}")

        # Register handle_message with telethon (global handler)
        @self.client.on(events.NewMessage())
        async def handle_message(event):
            try:
                channel_id = str(event.chat_id)
                channel_name = self.config.channel_names.get(channel_id, f"Unresolved:{channel_id}")

                msg_data = await self._create_message_data(event.message, channel_id)

                tg_id = getattr(msg_data.original_message, "id", None)
                logger.info(f"[TelegramHandler] Received message tg_id={tg_id} from {channel_name}")

                # Forward to the router
                await callback(msg_data, is_latest=False)

            except Exception as e:
                channel_name = self.config.channel_names.get(str(event.chat_id), f"Unresolved:{event.chat_id}")
                logger.error(f"[TelegramHandler] Error handling message from {channel_name}: {e}", exc_info=True)

    
    async def _create_message_data(self, message, channel_id: str) -> MessageData:
        """Create MessageData from Telegram message."""
        self._msg_counter += 1
        
        # Get username/display name
        username = "Unknown"
        if message.sender:
            if isinstance(message.sender, User):
                if message.sender.username:
                    username = f"@{message.sender.username}"
                elif message.sender.first_name:
                    username = message.sender.first_name
                    if message.sender.last_name:
                        username += f" {message.sender.last_name}"
            elif isinstance(message.sender, Channel):
                username = f"@{message.sender.username}" if message.sender.username else "Channel"
            else:
                username = f"@{getattr(message.sender, 'username', 'Unknown')}"
        
        # Get media type
        media_type = None
        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                media_type = "Photo"
            elif isinstance(message.media, MessageMediaDocument):
                media_type = "Document"
            else:
                media_type = "Other"
        
        # Get reply context if this is a reply
        reply_context = None
        if message.reply_to:
            reply_context = await self._get_reply_context(message)
        
        return MessageData(
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
    
    async def _get_reply_context(self, message) -> Optional[Dict]:
        """Extract context about what message this is replying to."""
        try:
            # Get the message being replied to
            replied_msg = await self.client.get_messages(
                message.chat_id,
                ids=message.reply_to.reply_to_msg_id
            )
            
            if replied_msg:
                # Extract author info
                author = "Unknown"
                if replied_msg.sender:
                    if isinstance(replied_msg.sender, User):
                        if replied_msg.sender.username:
                            author = f"@{replied_msg.sender.username}"
                        elif replied_msg.sender.first_name:
                            author = replied_msg.sender.first_name
                            if replied_msg.sender.last_name:
                                author += f" {replied_msg.sender.last_name}"
                    elif isinstance(replied_msg.sender, Channel):
                        author = f"@{replied_msg.sender.username}" if replied_msg.sender.username else "Channel"
                    else:
                        author = f"@{getattr(replied_msg.sender, 'username', 'Unknown')}"
                
                # Get media type if present
                media_type = None
                if replied_msg.media:
                    if isinstance(replied_msg.media, MessageMediaPhoto):
                        media_type = "Photo"
                    elif isinstance(replied_msg.media, MessageMediaDocument):
                        media_type = "Document"
                    else:
                        media_type = "Other"
                
                # Build context
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
        """Check if media is allowed under restricted mode rules."""
        if not message.media:
            return True
        
        if not isinstance(message.media, MessageMediaDocument):
            # Photos are blocked in restricted mode
            logger.info("[TelegramHandler] Media blocked by restricted mode: only documents are allowed in restricted mode")
            return False
        
        document = message.media.document

        extension_allowed = False
        mime_allowed = False
        ext = None
        mime = getattr(document, "mime_type", None)

        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    ext = os.path.splitext(attr.file_name.lower())[1]
                    if ext in self.ALLOWED_EXTENSIONS:
                        extension_allowed = True
                        break
        
        if mime and mime in self.ALLOWED_MIME_TYPES:
            mime_allowed = True

        allowed = extension_allowed and mime_allowed
        if not allowed:
            logger.info(
                f"[TelegramHandler] Media blocked by restricted mode: "
                f"type={type(message.media).__name__}, ext={ext}, mime={mime}"
            )
        return allowed

    async def download_media(self, msg_data: MessageData) -> Optional[str]:
        """Download attached media from message."""
        try:
            if msg_data.original_message and msg_data.original_message.media:
                target_dir = str(self.config.attachments_dir) + os.sep
                return await msg_data.original_message.download_media(file=target_dir)
        except Exception as e:
            logger.error(f"[TelegramHandler] Media download failed: {e}")
        return None
    
    async def run(self):
        """Keep client running."""
        await self.client.run_until_disconnected()
