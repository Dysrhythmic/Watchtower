import os
import asyncio
import logging
import requests
import json
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class MessageData:
    """Container for extracted message information"""
    username: str
    timestamp: object
    text: str
    media_type: Optional[str]
    has_media: bool
    reply_context: Optional[Dict] = None

@dataclass
class RoutingResult:
    """Container for routing decision results"""
    webhook_urls: List[str]
    matched_keywords: List[str]
    should_send: bool

def normalize_channel_id(channel_id) -> Optional[str]:
    """Convert any channel ID format to consistent string representation"""
    if not channel_id:
        return None
    
    channel_str = str(channel_id).strip()
    if not channel_str:
        return None
        
    # Handle @username format
    if channel_str.startswith('@'):
        return channel_str
    
    # Handle numeric IDs (including negative ones)
    if channel_str.lstrip('-').isdigit():
        return channel_str
    
    return channel_str

def format_message_content(channel_title, username, timestamp, content_type, message_text="", 
                         is_latest=False, reply_context=None, matched_keywords=None):
    """Formats message content for Discord webhooks with optional keyword matches"""
    prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
    content_parts = [
        f"**{prefix.lower().title()} from channel:** {channel_title}",
        f"**By:** {username}",
        f"**Time:** {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Content:** {content_type}"
    ]
    
    # Add matched keywords if any
    if matched_keywords:
        keywords_text = ", ".join(f"`{kw}`" for kw in matched_keywords)
        content_parts.append(f"**Matched keywords:** {keywords_text}")
    
    # Add reply context if available
    if reply_context:
        reply_author = reply_context.get('author', 'Unknown')
        reply_text = reply_context.get('text', '')
        reply_time = reply_context.get('time', '')
        
        reply_info = f"**Replying to:** {reply_author}"
        if reply_time:
            reply_info += f" ({reply_time})"
        if reply_text:
            truncated_reply = reply_text[:100] + "..." if len(reply_text) > 100 else reply_text
            reply_info += f"\n**Original message:** {truncated_reply}"
        
        content_parts.append(reply_info)
    
    if message_text:
        content_parts.append(f"**Message:**\n{message_text}")
    
    return "\n".join(content_parts)

class ConfigManager:
    """Simplified configuration manager with clear separation of routing modes"""
    
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_channel_ids = [
            id.strip() for id in os.getenv('TELEGRAM_CHANNEL_IDS', '').split(',') 
            if id.strip()
        ]
        self.default_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        self.config_file = os.getenv('WEBHOOK_CONFIG_FILE', 'webhook_config.json')
        
        self.webhook_config = self._load_webhook_config()
        self._validate_config()
    
    def _load_webhook_config(self) -> Optional[Dict]:
        """Load and resolve webhook configuration"""
        if not os.path.exists(self.config_file):
            logger.info(f"Webhook config file {self.config_file} not found")
            return None
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self._resolve_webhook_urls(config)
                logger.info(f"Loaded webhook configuration from {self.config_file}")
                return config
        except Exception as e:
            logger.error(f"Error loading webhook config: {e}")
            return None
    
    def _resolve_webhook_urls(self, config: Dict):
        """Resolve environment variable references to actual webhook URLs"""
        valid_webhooks = []
        
        for webhook in config.get('webhooks', []):
            env_key = webhook.get('env_key')
            if env_key:
                webhook_url = os.getenv(env_key)
                if webhook_url:
                    webhook['url'] = webhook_url
                    webhook.pop('env_key', None)
                    valid_webhooks.append(webhook)
                    logger.info(f"Resolved {env_key} to webhook URL")
                else:
                    logger.warning(f"Environment variable {env_key} not found, skipping webhook")
            else:
                valid_webhooks.append(webhook)
        
        config['webhooks'] = valid_webhooks
    
    def _validate_config(self):
        """Validate configuration completeness"""
        if not all([self.api_id, self.api_hash, self.telegram_channel_ids]):
            raise ValueError("Missing required environment variables: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHANNEL_IDS")
        
        if not self.default_webhook_url and not self.webhook_config:
            raise ValueError("Either DISCORD_WEBHOOK_URL or webhook config file must be provided")
    
    def has_advanced_routing(self) -> bool:
        """Check if advanced routing is available"""
        return self.webhook_config is not None
    
    def has_default_webhook(self) -> bool:
        """Check if default webhook is available"""
        return self.default_webhook_url is not None

class MessageRouter:
    """Clean message routing with keyword matching"""
    
    def __init__(self, webhook_config: Optional[Dict]):
        self.webhook_config = webhook_config
    
    def route_message(self, channel_id: str, message_text: str = "") -> RoutingResult:
        """
        Determine webhooks and matched keywords for a message
        Returns RoutingResult with webhook URLs and matched keywords
        """
        if not self.webhook_config:
            return RoutingResult(webhook_urls=[], matched_keywords=[], should_send=False)
        
        webhook_urls = []
        all_matched_keywords = []
        
        normalized_channel_id = normalize_channel_id(channel_id)
        message_lower = message_text.lower()
        
        for webhook in self.webhook_config.get('webhooks', []):
            webhook_url = webhook.get('url')
            if not webhook_url:
                continue
                
            webhook_matched_keywords = []
            
            for channel_config in webhook.get('channels', []):
                config_channel_id = normalize_channel_id(channel_config.get('id'))
                keywords = channel_config.get('keywords', [])
                
                if config_channel_id == normalized_channel_id:
                    if not keywords:
                        # No keywords = all messages from this channel
                        webhook_urls.append(webhook_url)
                        logger.info(f"Channel {channel_id} -> webhook (no keyword filter)")
                        break
                    else:
                        # Check for keyword matches
                        for keyword in keywords:
                            keyword_lower = keyword.lower()
                            if keyword_lower in message_lower:
                                webhook_matched_keywords.append(keyword)
                                logger.info(f"Keyword match found: '{keyword}' in channel {channel_id}")
                        
                        if webhook_matched_keywords:
                            webhook_urls.append(webhook_url)
                            all_matched_keywords.extend(webhook_matched_keywords)
                            logger.info(f"Channel {channel_id} -> webhook (keywords: {webhook_matched_keywords})")
                            break
                        else:
                            logger.info(f"No keyword matches found for channel {channel_id}")
                    
                    # Only match one channel config per webhook
                    break
        
        # Remove duplicate keywords while preserving order
        unique_keywords = []
        seen = set()
        for kw in all_matched_keywords:
            if kw not in seen:
                unique_keywords.append(kw)
                seen.add(kw)
        
        return RoutingResult(
            webhook_urls=webhook_urls,
            matched_keywords=unique_keywords,
            should_send=len(webhook_urls) > 0
        )
    
    def get_all_webhook_urls(self) -> List[str]:
        """Get all configured webhook URLs for notifications"""
        if not self.webhook_config:
            return []
        
        urls = set()
        for webhook in self.webhook_config.get('webhooks', []):
            if webhook.get('url'):
                urls.add(webhook['url'])
        return list(urls)

class DiscordHandler:
    """Simplified Discord webhook handler"""
    
    DISCORD_MAX_LENGTH = 2000
    DISCORD_SUCCESS_CODES = [200, 204]
    
    def __init__(self, default_webhook_url: Optional[str] = None):
        self.default_webhook_url = default_webhook_url
    
    def send_to_webhooks(self, message: str, webhook_urls: List[str]) -> bool:
        """Send message to multiple webhooks"""
        if not webhook_urls:
            return False
            
        success = True
        for url in webhook_urls:
            if not self._send_message(message, url):
                success = False
        return success
    
    def send_to_default(self, message: str) -> bool:
        """Send message to default webhook"""
        if not self.default_webhook_url:
            return False
        return self._send_message(message, self.default_webhook_url)
    
    def _send_message(self, message: str, webhook_url: str) -> bool:
        """Send message with automatic chunking if needed"""
        if len(message) <= self.DISCORD_MAX_LENGTH:
            return self._make_request(message, webhook_url)
        
        # Chunk long messages
        chunks = [message[i:i+self.DISCORD_MAX_LENGTH] 
                 for i in range(0, len(message), self.DISCORD_MAX_LENGTH)]
        
        success = True
        for chunk in chunks:
            if not self._make_request(chunk, webhook_url):
                success = False
        return success
    
    def _make_request(self, content: str, webhook_url: str) -> bool:
        """Make HTTP request to Discord webhook"""
        try:
            payload = {"content": content, "username": "Telecord"}
            response = requests.post(webhook_url, json=payload, timeout=10)
            
            if response.status_code in self.DISCORD_SUCCESS_CODES:
                logger.info("Message sent to Discord successfully")
                return True
            else:
                logger.error(f"Discord webhook failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending to Discord: {e}")
            return False
    
    async def send_media_to_webhooks(self, file_path: str, media_type: str, 
                                   channel_title: str, username: str, timestamp: object,
                                   webhook_urls: List[str], message_text: str = "",
                                   is_latest: bool = False, reply_context: Optional[Dict] = None,
                                   matched_keywords: Optional[List[str]] = None) -> bool:
        """Send media to multiple webhooks"""
        if not webhook_urls:
            return False
            
        success = True
        for url in webhook_urls:
            if not await self._send_media(file_path, media_type, channel_title, username, 
                                        timestamp, url, message_text, is_latest, 
                                        reply_context, matched_keywords, cleanup=False):
                success = False
        
        # Cleanup after all sends
        self._cleanup_file(file_path)
        return success
    
    async def send_media_to_default(self, file_path: str, media_type: str,
                                  channel_title: str, username: str, timestamp: object,
                                  message_text: str = "", is_latest: bool = False,
                                  reply_context: Optional[Dict] = None,
                                  matched_keywords: Optional[List[str]] = None) -> bool:
        """Send media to default webhook"""
        if not self.default_webhook_url:
            return False
        return await self._send_media(file_path, media_type, channel_title, username,
                                    timestamp, self.default_webhook_url, message_text,
                                    is_latest, reply_context, matched_keywords, cleanup=True)
    
    async def _send_media(self, file_path: str, media_type: str, channel_title: str,
                        username: str, timestamp: object, webhook_url: str,
                        message_text: str = "", is_latest: bool = False,
                        reply_context: Optional[Dict] = None,
                        matched_keywords: Optional[List[str]] = None,
                        cleanup: bool = True) -> bool:
        """Send media file to specific webhook"""
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                
                content = format_message_content(
                    channel_title, username, timestamp, media_type, message_text,
                    is_latest, reply_context, matched_keywords
                )
                
                data = {'username': 'Telecord', 'content': content}
                response = requests.post(webhook_url, files=files, data=data, timeout=30)
                
                if response.status_code in self.DISCORD_SUCCESS_CODES:
                    logger.info(f"Media ({media_type}) sent to Discord successfully")
                    return True
                else:
                    logger.error(f"Failed to send media: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error sending media: {e}")
            return False
        finally:
            if cleanup:
                self._cleanup_file(file_path)
    
    def _cleanup_file(self, file_path: str):
        """Remove temporary file"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")

class TelegramHandler:
    """Simplified Telegram operations"""
    
    def __init__(self, api_id: str, api_hash: str, channel_ids: List[str]):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel_ids = channel_ids
        self.client = TelegramClient('telecord_session', api_id, api_hash)
    
    async def start(self):
        """Start Telegram client"""
        await self.client.start()
    
    async def get_channel_info(self, channel_id: str) -> Tuple[object, str]:
        """Get channel entity and title"""
        # Convert string channel IDs to int if they're numeric (including negative)
        if isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
            channel_id = int(channel_id)
        
        channel = await self.client.get_entity(channel_id)
        title = getattr(channel, 'title', None) or getattr(channel, 'username', str(channel_id))
        return channel, title
    
    def extract_message_data(self, message) -> MessageData:
        """Extract all relevant data from a Telegram message"""
        username = self._extract_username(message.sender)
        timestamp = message.date
        text = message.text or ""
        media_type = self._get_media_type(message)
        has_media = media_type is not None
        
        return MessageData(
            username=username,
            timestamp=timestamp,
            text=text,
            media_type=media_type,
            has_media=has_media
        )
    
    def _extract_username(self, sender) -> str:
        """Extract username from sender"""
        if not sender:
            return "Unknown"
        
        if hasattr(sender, 'username') and sender.username:
            return f"@{sender.username}"
        elif hasattr(sender, 'first_name') and sender.first_name:
            username = sender.first_name
            if hasattr(sender, 'last_name') and sender.last_name:
                username += f" {sender.last_name}"
            return username
        return "Unknown"
    
    def _get_media_type(self, message) -> Optional[str]:
        """Get media type from message"""
        if not message.media:
            return None
            
        if isinstance(message.media, MessageMediaPhoto):
            return "Photo"
        elif isinstance(message.media, MessageMediaDocument):
            return "Document"
        elif isinstance(message.media, MessageMediaWebPage):
            return "Web Page"
        else:
            return "Other Media"
    
    async def get_reply_context(self, message) -> Optional[Dict]:
        """Get reply context if message is a reply"""
        try:
            if hasattr(message, 'reply_to') and message.reply_to:
                replied_message = await self.client.get_messages(
                    message.chat_id, 
                    ids=message.reply_to.reply_to_msg_id
                )
                
                if replied_message:
                    return {
                        'author': self._extract_username(replied_message.sender),
                        'text': replied_message.text or "",
                        'time': replied_message.date.strftime('%Y-%m-%d %H:%M:%S UTC') if replied_message.date else ""
                    }
        except Exception as e:
            logger.error(f"Error getting reply context: {e}")
        
        return None
    
    async def download_media(self, message) -> Optional[str]:
        """Download media from message"""
        try:
            if message.media:
                file_path = await message.download_media()
                logger.info(f"Downloaded media: {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
        return None
    
    async def get_latest_message(self, channel):
        """Get most recent message from channel"""
        async for message in self.client.iter_messages(channel, limit=1):
            return message
        return None
    
    async def run_until_disconnected(self):
        """Keep client running"""
        await self.client.run_until_disconnected()

    async def resolve_channel_username(self, channel_id: str) -> str:
        """Convert numeric channel ID to @username format if possible"""
        try:
            # If it's already a username format, return as is
            if channel_id.startswith('@'):
                return channel_id
            
            # If it's numeric, try to resolve to username
            if channel_id.lstrip('-').isdigit():
                channel_id_int = int(channel_id)
                channel = await self.client.get_entity(channel_id_int)
                if hasattr(channel, 'username') and channel.username:
                    return f"@{channel.username}"
            
            # Fallback to original ID
            return channel_id
        except Exception as e:
            logger.error(f"Error resolving channel ID {channel_id}: {e}")
            return channel_id

class Telecord:
    """Main Telecord orchestrator - simplified and focused"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.telegram = TelegramHandler(
            self.config.api_id, 
            self.config.api_hash, 
            self.config.telegram_channel_ids
        )
        self.discord = DiscordHandler(self.config.default_webhook_url)
        self.router = MessageRouter(self.config.webhook_config)
    
    async def start(self):
        """Start Telecord service"""
        await self.telegram.start()
        logger.info("Starting Telecord...")
        logger.info(f"Monitoring channels: {', '.join(self.config.telegram_channel_ids)}")
        
        self._log_configuration()
        await self._post_startup_messages()
        await self._setup_message_handler()
        await self.telegram.run_until_disconnected()
    
    def _log_configuration(self):
        """Log current configuration"""
        if self.config.has_advanced_routing():
            webhook_count = len(self.router.get_all_webhook_urls())
            logger.info(f"Advanced routing enabled with {webhook_count} webhooks")
        elif self.config.has_default_webhook():
            logger.info("Simple routing enabled with default webhook")
    
    async def _post_startup_messages(self):
        """Post latest messages and startup notification"""
        seen_channels = set()
        
        for channel_id in self.config.telegram_channel_ids:
            if not channel_id or channel_id in seen_channels:
                continue
            seen_channels.add(channel_id)
            
            try:
                channel, title = await self.telegram.get_channel_info(channel_id)
                logger.info(f"Processing channel: {channel_id} (resolved as: {title})")
                
                latest_message = await self.telegram.get_latest_message(channel)
                if latest_message:
                    await self._process_message(latest_message, title, channel_id, is_latest=True)
                    
            except Exception as e:
                logger.error(f"Error fetching latest message from {channel_id}: {e}")
        
        await self._send_startup_notification()
        logger.info("Telecord is now monitoring for new messages.")
    
    async def _send_startup_notification(self):
        """Send startup notification to all webhooks"""
        message = "**Telecord is now monitoring for new messages.**"
        
        if self.config.has_advanced_routing():
            webhook_urls = self.router.get_all_webhook_urls()
            self.discord.send_to_webhooks(message, webhook_urls)
        elif self.config.has_default_webhook():
            self.discord.send_to_default(message)
    
    async def _setup_message_handler(self):
        """Setup Telegram message event handler"""
        # Convert channel IDs to proper format for Telethon
        processed_channels = []
        for channel_id in self.config.telegram_channel_ids:
            if isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
                processed_channels.append(int(channel_id))
            else:
                processed_channels.append(channel_id)
        
        @self.telegram.client.on(events.NewMessage(chats=processed_channels))
        async def handle_message(event):
            try:
                message = event.message
                channel = await event.get_chat()
                title = getattr(channel, 'title', None) or getattr(channel, 'username', str(channel.id))
                await self._process_message(message, title, str(channel.id))
            except Exception as e:
                logger.error(f"Error handling new message: {e}")
    
    async def _process_message(self, message, channel_title: str, channel_id: str, is_latest: bool = False):
        """Main message processing pipeline"""
        # Extract message data
        msg_data = self.telegram.extract_message_data(message)
        msg_data.reply_context = await self.telegram.get_reply_context(message)
        
        # Resolve channel ID to username format for proper routing
        resolved_channel_id = await self.telegram.resolve_channel_username(channel_id)
        logger.info(f"Resolved channel ID: {channel_id} -> {resolved_channel_id}")
        
        # Route message
        routing = self.router.route_message(resolved_channel_id, msg_data.text)
        
        # Fallback to default webhook if advanced routing didn't match
        if not routing.should_send and self.config.has_default_webhook():
            routing = RoutingResult(
                webhook_urls=[self.config.default_webhook_url],
                matched_keywords=[],
                should_send=True
            )
        
        # Log message info
        self._log_message(channel_title, msg_data, routing.matched_keywords, is_latest)
        
        if not routing.should_send:
            # Only log if we have advanced routing (don't spam for missing default webhook)
            if self.config.has_advanced_routing():
                logger.info(f"Message filtered out - no keyword matches")
            return
        
        # Send message
        await self._send_message(message, msg_data, routing, channel_title, is_latest)
    
    def _log_message(self, channel_title: str, msg_data: MessageData, matched_keywords: List[str], is_latest: bool):
        """Log message information"""
        prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
        logger.info("=" * 60)
        logger.info(f"{prefix} from {channel_title}:")
        logger.info(f"By: {msg_data.username}")
        logger.info(f"Time: {msg_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if matched_keywords:
            logger.info(f"Matched keywords: {', '.join(matched_keywords)}")
        if msg_data.text:
            logger.info(f"Message: {msg_data.text}")
        if msg_data.media_type:
            logger.info(f"Media: {msg_data.media_type}")
        logger.info("=" * 60)
    
    async def _send_message(self, message, msg_data: MessageData, routing: RoutingResult, 
                          channel_title: str, is_latest: bool):
        """Send message to Discord based on content type"""
        if msg_data.has_media:
            await self._send_media_message(message, msg_data, routing, channel_title, is_latest)
        else:
            await self._send_text_message(msg_data, routing, channel_title, is_latest)
    
    async def _send_media_message(self, message, msg_data: MessageData, routing: RoutingResult,
                                channel_title: str, is_latest: bool):
        """Send media message to Discord"""
        # Download media from the original message
        file_path = await self.telegram.download_media(message)
        
        if file_path:
            # Send media to webhooks
            if routing.webhook_urls:
                await self.discord.send_media_to_webhooks(
                    file_path, msg_data.media_type, channel_title, msg_data.username,
                    msg_data.timestamp, routing.webhook_urls, msg_data.text, is_latest,
                    msg_data.reply_context, routing.matched_keywords
                )
            else:
                await self.discord.send_media_to_default(
                    file_path, msg_data.media_type, channel_title, msg_data.username,
                    msg_data.timestamp, msg_data.text, is_latest,
                    msg_data.reply_context, routing.matched_keywords
                )
        else:
            # Fallback to text message if download fails
            content_type = f"{msg_data.media_type} with caption" if msg_data.text else f"{msg_data.media_type} (download failed)"
            discord_message = format_message_content(
                channel_title, msg_data.username, msg_data.timestamp, content_type,
                msg_data.text, is_latest, msg_data.reply_context, routing.matched_keywords
            )
            
            if routing.webhook_urls:
                self.discord.send_to_webhooks(discord_message, routing.webhook_urls)
            else:
                self.discord.send_to_default(discord_message)
    
    async def _send_text_message(self, msg_data: MessageData, routing: RoutingResult,
                               channel_title: str, is_latest: bool):
        """Send text message to Discord"""
        discord_message = format_message_content(
            channel_title, msg_data.username, msg_data.timestamp, "Text",
            msg_data.text, is_latest, msg_data.reply_context, routing.matched_keywords
        )
        
        if routing.webhook_urls:
            self.discord.send_to_webhooks(discord_message, routing.webhook_urls)
        else:
            self.discord.send_to_default(discord_message)

def main():
    """Application entry point"""
    try:
        telecord = Telecord()
        asyncio.run(telecord.start())
    except KeyboardInterrupt:
        logger.info("Telecord stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == "__main__":
    main() 
