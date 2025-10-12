import os
import asyncio
import logging
import requests
import json
from telethon import TelegramClient, events, utils
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, Channel, User
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Optional, Dict, Set

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class MessageData:
    """Container for extracted message information from Telegram."""
    msg_id: int
    channel_id: str
    channel_name: str
    username: str
    timestamp: object
    text: str
    has_media: bool
    media_type: Optional[str] = None
    media_path: Optional[str] = None
    reply_context: Optional[Dict] = None 
    original_message: Optional[object] = None

class ConfigManager:
    """Manages configuration from environment variables and JSON config."""
    
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        
        if not all([self.api_id, self.api_hash]):
            raise ValueError("Missing required: TELEGRAM_API_ID, TELEGRAM_API_HASH")
        
        # Load webhook configuration
        config_file = os.getenv('WEBHOOK_CONFIG_FILE', 'webhook_config.json')
        self.webhooks = self._load_webhooks(config_file)
        self.channel_names = {}  # channel_id -> friendly name mapping for display/logging
        
        logger.info(f"[ConfigManager] Loaded {len(self.webhooks)} webhooks")
    
    def _load_webhooks(self, config_file: str) -> List[Dict]:
        """Load and validate webhook configuration."""
        if not os.path.exists(config_file):
            raise ValueError(f"Config file {config_file} not found")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        webhooks = []
        for webhook in config.get('webhooks', []):
            name = webhook.get('name', 'Unnamed')
            
            # Resolve webhook URL
            if 'env_key' in webhook:
                url = os.getenv(webhook['env_key'])
                if not url:
                    logger.warning(f"[ConfigManager] Missing environment variable {webhook['env_key']} for {name}")
                    continue
            elif 'url' in webhook:
                url = webhook['url']
            else:
                logger.warning(f"[ConfigManager] No URL for webhook {name}")
                continue
            
            # Validate channels
            channels = webhook.get('channels', [])
            if not channels or not all('id' in channel for channel in channels):
                logger.warning(f"[ConfigManager] Invalid channels for webhook {name}")
                continue
            
            # Log restricted mode settings for channels
            for channel in channels:
                if channel.get('restricted_mode', False):
                    logger.info(f"[ConfigManager] Restricted mode enabled for channel {channel['id']}")
            
            webhooks.append({
                'name': name,
                'url': url,
                'channels': channels
            })
        
        if not webhooks:
            raise ValueError("[ConfigManager] No valid webhooks configured")
        
        return webhooks
    
    def get_all_channel_ids(self) -> Set[str]:
        """Get all unique channel IDs from webhook config."""
        ids = set()
        for webhook in self.webhooks:
            for channel in webhook['channels']:
                ids.add(channel['id'])
        return ids

class MessageRouter:
    """Routes messages to webhooks based on configuration."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.channel_mappings = {}
    
    def is_channel_restricted(self, channel_id: str, channel_name: str) -> bool:
        """Check if any webhook has restricted mode enabled for this channel."""
        for webhook in self.config.webhooks:
            for channel in webhook['channels']:
                if self._channel_matches(channel_id, channel_name, channel['id']):
                    if channel.get('restricted_mode', False):
                        return True
        return False
    
    def add_channel_mapping(self, config_id: str, actual_id: str):
        """Store mapping between configured ID and actual channel ID."""
        self.channel_mappings[config_id] = actual_id
    
    def get_destinations(self, msg: MessageData) -> List[Dict]:
        """Get list of webhooks that should receive this message."""
        destinations = []
        
        for webhook in self.config.webhooks:
            # Find matching channel config
            channel_config = None
            for channel in webhook['channels']:
                if self._channel_matches(msg.channel_id, msg.channel_name, channel['id']):
                    channel_config = channel
                    break
            
            if not channel_config:
                continue
            
            # Check keywords
            keywords = channel_config.get('keywords')
            if keywords is None:
                # No keywords field, forward all
                destinations.append({
                    'name': webhook['name'],
                    'url': webhook['url'],
                    'keywords': [],
                    'restricted_mode': channel_config.get('restricted_mode', False),
                    'parser': channel_config.get('parser', 0)
                })
            elif keywords and msg.text:
                # Check for keyword matches
                matched = [keyword for keyword in keywords if keyword.lower() in msg.text.lower()]
                if matched:
                    destinations.append({
                        'name': webhook['name'],
                        'url': webhook['url'],
                        'keywords': matched,
                        'restricted_mode': channel_config.get('restricted_mode', False),
                        'parser': channel_config.get('parser', 0)
                    })
        
        return destinations
    
    def parse_msg(self, msg: MessageData, line_slice: int) -> MessageData:
        """Applies parsing to a message, currently just handles line removal"""
        if line_slice == 0 or not msg.text:
            return msg

        lines = msg.text.split('\n')
        # remove from start
        if line_slice > 0:
            lines = lines[line_slice:]
        # remove from end
        else:
            lines = lines[:line_slice]
        parsed_text = '\n'.join(lines)

        # Indicate if parsing removed all content
        if not parsed_text:
            if line_slice > 0:
                parsed_text = f"*[Message content removed by parser: first {line_slice} line(s) stripped]*"
            else:
                parsed_text = f"*[Message content removed by parser: last {abs(line_slice)} line(s) stripped]*"

        # return new msg object with parsed text and reference to original text
        return MessageData(
            msg_id=msg.msg_id,
            channel_id=msg.channel_id,
            channel_name=msg.channel_name,
            username=msg.username,
            timestamp=msg.timestamp,
            text=parsed_text,
            has_media=msg.has_media,
            media_type=msg.media_type,
            media_path=msg.media_path,
            reply_context=msg.reply_context,
            original_message=msg.original_message
        )
    
    def _channel_matches(self, channel_id: str, channel_name: str, config_id: str) -> bool:
        """Check if channel matches configuration."""
        # Direct matches
        if channel_id == config_id or channel_name == config_id:
            return True
        
        # Handle -100 prefix for supergroups
        if f"-100{channel_id}" == config_id:
            return True
        
        # Handle numeric IDs without -100 prefix
        if config_id.isdigit() and channel_id == f"-100{config_id}":
            return True
        
        return False

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
        self.client = TelegramClient('telecord_session', config.api_id, config.api_hash)
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
            channel_name = self.config.channel_names.get(channel_id, f"Channel-{channel_id}")
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
        
        # Register handle_message with telethon
        channel_ids = list(map(int, self.channels.keys()))
        
        @self.client.on(events.NewMessage(chats=channel_ids))
        async def handle_message(event):
            try:
                channel_id = str(event.chat_id)
                msg_data = await self._create_message_data(event.message, channel_id)
                await callback(msg_data, is_latest=False)
            except Exception as e:
                channel_name = self.config.channel_names.get(str(event.chat_id), f"Channel-{event.chat_id}")
                logger.error(f"[TelegramHandler] Error handling message from {channel_name}: {e}", exc_info=True)
        
        logger.info(f"[TelegramHandler] Event handlers configured for {len(channel_ids)} channels")
    
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
            msg_id=self._msg_counter,
            channel_id=channel_id,
            channel_name=self.config.channel_names.get(channel_id, f"Channel-{channel_id}"),
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
            return False
        
        document = message.media.document
        
        extension_allowed = False
        mime_allowed = False
        
        # Check file extension
        if hasattr(document, 'attributes'):
            for attr in document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    ext = os.path.splitext(attr.file_name.lower())[1]
                    if ext in self.ALLOWED_EXTENSIONS:
                        extension_allowed = True
                        break
        
        # Check MIME type
        if hasattr(document, 'mime_type') and document.mime_type:
            if document.mime_type in self.ALLOWED_MIME_TYPES:
                mime_allowed = True
        
        return extension_allowed and mime_allowed
    
    async def download_media(self, msg_data: MessageData, restricted_mode: bool = False) -> Optional[str]:
        """Download attached media from message."""
        try:
            if msg_data.original_message and msg_data.original_message.media:
                # Check restrictions if in restricted mode
                if restricted_mode and not self._is_media_restricted(msg_data.original_message):
                    logger.info(f"[TelegramHandler] Media blocked by restricted mode: {msg_data.media_type}")
                    return None
                
                return await msg_data.original_message.download_media()
        except Exception as e:
            logger.error(f"[TelegramHandler] Media download failed: {e}")
        return None
    
    async def run(self):
        """Keep client running."""
        await self.client.run_until_disconnected()

class DiscordHandler:
    """Handles Discord webhook operations."""
    
    MAX_LENGTH = 2000
    
    def send_message(self, content: str, url: str, media_path: Optional[str] = None) -> bool:
        """Send message to Discord webhook."""
        try:
            chunks = self._chunk_text(content)
            chunks_sent = 0
            
            if media_path and os.path.exists(media_path):
                # Send first chunk with media
                with open(media_path, 'rb') as f:
                    files = {'file': f}
                    data = {'username': 'Telecord', 'content': chunks[0]}
                    response = requests.post(url, files=files, data=data, timeout=15)
                    if response.status_code not in [200, 204]:
                        return False
                    chunks_sent = 1

            # Send text content
            for chunk in chunks[chunks_sent:]:
                payload = {"username": "Telecord", "content": chunk}
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code not in [200, 204]:
                    return False
                chunks_sent += 1
            
            return True
            
        except Exception as e:
            logger.error(f"[DiscordHandler] Discord send failed: {e}")
            return False
    
    def _chunk_text(self, text: str) -> List[str]:
        """Split text into Discord compatible chunks."""
        if len(text) <= self.MAX_LENGTH:
            return [text]
        
        chunks = []
        while text:
            if len(text) <= self.MAX_LENGTH:
                chunks.append(text)
                break
            
            # Split on newlines where possible
            split_point = text.rfind('\n', 0, self.MAX_LENGTH)
            if split_point == -1:
                split_point = self.MAX_LENGTH
            
            chunks.append(text[:split_point])
            text = text[split_point:].lstrip('\n')
        
        return chunks
    
    def format_message(self, msg: MessageData, dest: Dict) -> str:
        """Format message for Discord."""
        lines = [
            f"**New message from:** {msg.channel_name}",
            f"**By:** {msg.username}",
            f"**Time:** {msg.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ]
        
        if msg.has_media:
            lines.append(f"**Content:** {msg.media_type}")
        
        if dest['keywords']:
            lines.append(f"**Matched:** {', '.join(f'`{keyword}`' for keyword in dest['keywords'])}")
        
        if msg.reply_context:
            lines.append(self._format_reply_context(msg.reply_context))
        
        if msg.text:
            lines.append(f"**Message:**\n{msg.text}")
        
        return '\n'.join(lines)
    
    def _format_reply_context(self, reply_context: Dict) -> str:
        """Format reply context for Discord display."""
        parts = []
        
        parts.append(f"**  Replying to:** {reply_context['author']} ({reply_context['time']})")
        
        if reply_context.get('has_media'):
            media_type = reply_context.get('media_type', 'Other')
            parts.append(f"**  Original content:** {media_type}")
        
        # Original message text (truncate if too long)
        original_text = reply_context.get('text', '')
        if original_text:
            if len(original_text) > 200:
                original_text = original_text[:200] + " ..."
            parts.append(f"**  Original message:** {original_text}")
        elif reply_context.get('has_media'):
            parts.append("**  Original message:** [Media only, no caption]")
        
        return '\n'.join(parts)

class Telecord:
    """Main application coordinating all components."""
    
    def __init__(self):
        self.config = ConfigManager()
        self.telegram = TelegramHandler(self.config)
        self.router = MessageRouter(self.config)
        self.discord = DiscordHandler()
        
        logger.info("[Telecord] Initialized")
    
    async def start(self):
        """Start the service."""
        
        await self.telegram.start()
        
        # Setup message handler
        self.telegram.setup_handlers(self._handle_message)
        
        # Log connection proofs
        await self.telegram.fetch_latest_messages()
        
        logger.info("[Telecord] Now monitoring for new messages...")
        
        await self.telegram.run()
    
    async def _handle_message(self, msg: MessageData, is_latest: bool):
        """Process incoming message."""
        try:
            # If this is a connection proof message, just log it instead of sending to Discord
            if is_latest:
                logger.info(f"\n[Telecord] CONNECTION ESTABLISHED\n"
                        f"  Channel: {msg.channel_name}\n"
                        f"  Latest message by: {msg.username}\n"
                        f"  Time: {msg.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                return
            
            # Get destinations
            destinations = self.router.get_destinations(msg)
            
            if not destinations:
                logger.info(f"[Telecord] Message from {msg.channel_name} by {msg.username} has no destinations")
                return
            
            # Determine if media should be downloaded
            should_download = False
            if msg.has_media:
                # Check if media passes restricted mode checks without downloading
                media_passes_restrictions = self.telegram._is_media_restricted(msg.original_message)
                
                # Set flag to download if at least one destination would accept it
                for dest in destinations:
                    if not dest.get('restricted_mode', False):  # Unrestricted always accepts
                        should_download = True
                        break
                    elif media_passes_restrictions:  # Restricted but media is allowed type
                        should_download = True
                        break
            
            # Download media if needed
            if should_download:
                msg.media_path = await self.telegram.download_media(msg, restricted_mode=False)
            
            # Send to each destination
            for dest in destinations:
                # Parse msg for this specific destination
                parsed_msg = self.router.parse_msg(msg, dest['parser'])
                # Determine if this destination gets the media
                include_media = False
                if msg.media_path:
                    # Unrestricted destinations always get media
                    # Restricted destinations get allowed media types
                    if not dest.get('restricted_mode', False) or media_passes_restrictions:
                        include_media = True  
                
                content = self.discord.format_message(parsed_msg, dest)
                
                if msg.has_media and not include_media:
                    if dest.get('restricted_mode', False):
                        content += "\n*[Media attachment filtered due to restricted mode]*"
                    else:
                        content += f"\n*[Media type {msg.media_type} could not be forwarded to Discord]*"
                
                # Send with or without media based on this destination's rules
                media_to_send = msg.media_path if include_media else None
                success = self.discord.send_message(content, dest['url'], media_to_send)
                
                status = "sent" if success else "failed"
                logger.info(f"[Telecord] Message from {msg.channel_name} by {msg.username} {status} to {dest['name']}")
        
        except Exception as e:
            logger.error(f"[Telecord] Error processing message from {msg.channel_name} by {msg.username}: {e}", exc_info=True)
        
        # Clean up media file after all destinations have been processed
        if msg.media_path and os.path.exists(msg.media_path):
            try:
                os.remove(msg.media_path)
            except:
                pass

def main():
    try:
        app = Telecord()
        asyncio.run(app.start())
    except KeyboardInterrupt:
        logger.info("[main] Stopped by user")
    except Exception as e:
        logger.error(f"[main] Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()