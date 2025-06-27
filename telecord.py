import os
import asyncio
import logging
import requests
import json
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ConfigManager:
    """Handles all configuration loading and validation."""
    
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_channel_ids = os.getenv('TELEGRAM_CHANNEL_IDS', '').split(',')
        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        self.config_file = os.getenv('WEBHOOK_CONFIG_FILE', 'webhook_config.json')
        
        if not self.discord_webhook_url:
            self.webhook_config = self._load_webhook_config()
        else:
            self.webhook_config = None
            logger.info("Using simple routing mode with default webhook")
        
        self._validate_config()
    
    def _load_webhook_config(self):
        if not os.path.exists(self.config_file):
            logger.info(f"Webhook config file {self.config_file} not found, using default webhook")
            return None
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded webhook configuration from {self.config_file}")
                
                self._resolve_webhook_urls(config)
                
                return config
        except Exception as e:
            logger.error(f"Error loading webhook config from {self.config_file}: {e}")
            return None
    
    def _resolve_webhook_urls(self, config):
        """Resolve environment variable references to actual webhook URLs."""
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
                    if not self.discord_webhook_url:
                        logger.warning(f"Environment variable {env_key} not found, skipping webhook")
            else:
                valid_webhooks.append(webhook)
        
        config['webhooks'] = valid_webhooks
    
    def _validate_config(self):
        if not all([self.api_id, self.api_hash, self.telegram_channel_ids]):
            raise ValueError("Missing required environment variables. Please check TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_CHANNEL_IDS")
        
        if not self.discord_webhook_url and not self.webhook_config:
            raise ValueError(f"Either DISCORD_WEBHOOK_URL or {self.config_file} must be provided")
        
        if self.discord_webhook_url and self.webhook_config:
            logger.info("Using advanced routing mode with fallback to default webhook")
        elif self.discord_webhook_url:
            logger.info("Using simple routing mode (all messages to default webhook)")
        else:
            logger.info("Using advanced routing mode only")
    
    def get_telegram_credentials(self):
        return self.api_id, self.api_hash
    
    def get_channel_ids(self):
        return self.telegram_channel_ids
    
    def get_webhook_config(self):
        return self.webhook_config
    
    def get_default_webhook(self):
        return self.discord_webhook_url
    
    def get_config_file_path(self):
        return self.config_file

class DiscordHandler:
    """Handles all Discord webhook operations."""
    
    DISCORD_MAX_LENGTH = 2000
    DISCORD_SUCCESS_CODES = [200, 204]
    
    def __init__(self, default_webhook_url=None):
        self.default_webhook_url = default_webhook_url
    
    def send_to_multiple_webhooks(self, message, webhook_urls):
        if not webhook_urls:
            logger.warning("No webhook URLs provided")
            return False
            
        success = True
        for webhook_url in webhook_urls:
            if not self._send_to_specific_webhook(message, webhook_url):
                success = False
        return success
    
    def _send_to_specific_webhook(self, message, webhook_url):
        if len(message) <= self.DISCORD_MAX_LENGTH:
            return self._send_single_message_to_webhook(message, webhook_url)
        else:
            return self._send_chunked_message_to_webhook(message, webhook_url)
    
    def _send_single_message_to_webhook(self, message, webhook_url):
        payload = {
            "content": message,
            "username": "Telecord"
        }
        return self._make_discord_request(payload, "Message", webhook_url)
    
    def _send_chunked_message_to_webhook(self, message, webhook_url):
        chunks = [message[i:i+self.DISCORD_MAX_LENGTH] for i in range(0, len(message), self.DISCORD_MAX_LENGTH)]
        success = True
        
        for idx, chunk in enumerate(chunks):
            payload = {
                "content": chunk,
                "username": "Telecord"
            }
            if not self._make_discord_request(payload, f"Message chunk {idx+1}/{len(chunks)}", webhook_url):
                success = False
        
        return success
    
    def send_to_discord(self, message):
        if len(message) <= self.DISCORD_MAX_LENGTH:
            return self._send_single_message(message)
        else:
            return self._send_chunked_message(message)
    
    def _send_single_message(self, message):
        payload = {
            "content": message,
            "username": "Telecord"
        }
        return self._make_discord_request(payload, "Message")
    
    def _send_chunked_message(self, message):
        chunks = [message[i:i+self.DISCORD_MAX_LENGTH] for i in range(0, len(message), self.DISCORD_MAX_LENGTH)]
        success = True
        
        for idx, chunk in enumerate(chunks):
            payload = {
                "content": chunk,
                "username": "Telecord"
            }
            if not self._make_discord_request(payload, f"Message chunk {idx+1}/{len(chunks)}"):
                success = False
        
        return success
    
    def _make_discord_request(self, payload, description, webhook_url=None):
        target_webhook = webhook_url or self.default_webhook_url
        if not target_webhook:
            logger.error(f"No webhook URL available for {description}")
            return False
            
        try:
            response = requests.post(
                target_webhook,
                json=payload,
                timeout=10
            )
            if response.status_code in self.DISCORD_SUCCESS_CODES:
                logger.info(f"{description} sent to Discord successfully")
                return True
            else:
                logger.error(f"Failed to send {description.lower()} to Discord: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending {description.lower()} to Discord: {e}")
            return False
    
    async def send_media_to_discord(self, file_path, media_type, channel_title, username, timestamp, message_text="", is_latest=False, webhook_url=None):
        target_webhook = webhook_url or self.default_webhook_url
        if not target_webhook:
            logger.error(f"No webhook URL available for media ({media_type})")
            return False
            
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                
                full_content = self._format_discord_message(
                    channel_title, username, timestamp, media_type, message_text, is_latest
                )
                
                data = {
                    'username': 'Telecord',
                    'content': full_content
                }
                response = requests.post(
                    target_webhook,
                    files=files,
                    data=data,
                    timeout=30
                )
                if response.status_code in self.DISCORD_SUCCESS_CODES:
                    logger.info(f"Media ({media_type}) sent to Discord successfully")
                    return True
                else:
                    logger.error(f"Failed to send media to Discord: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending media to Discord: {e}")
            return False
        finally:
            self._cleanup_temp_file(file_path)
    
    def _format_discord_message(self, channel_title, username, timestamp, content_type, message_text="", is_latest=False):
        prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
        content_parts = [
            f"**{prefix.lower().title()} from channel:** {channel_title}",
            f"**From:** {username}",
            f"**Time:** {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Content:** {content_type}"
        ]
        
        if message_text:
            content_parts.append(f"**Message:**\n{message_text}")
        
        return "\n".join(content_parts)
    
    def _cleanup_temp_file(self, file_path):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")
    
    async def send_media_to_multiple_webhooks(self, file_path, media_type, channel_title, username, timestamp, message_text="", is_latest=False, webhook_urls=None):
        if not webhook_urls:
            logger.warning("No webhook URLs provided for media")
            return False
            
        success = True
        for webhook_url in webhook_urls:
            if not await self.send_media_to_discord(file_path, media_type, channel_title, username, timestamp, message_text, is_latest, webhook_url):
                success = False
        return success

class MessageRouter:
    """Handles message routing and filtering logic."""
    
    def __init__(self, webhook_config):
        self.webhook_config = webhook_config
    
    def _normalize_channel_id(self, channel_id):
        if not channel_id:
            return channel_id
            
        channel_id_str = str(channel_id)
        
        return channel_id_str
    
    def get_webhooks_for_message(self, channel_id, message_text=""):
        if not self.webhook_config:
            return []
        
        webhook_urls = []
        message_text_lower = message_text.lower()
        
        normalized_channel_id = self._normalize_channel_id(channel_id)
        
        for webhook in self.webhook_config.get('webhooks', []):
            webhook_url = webhook.get('url')
            if not webhook_url:
                continue
                
            for channel_config in webhook.get('channels', []):
                config_channel_id = self._normalize_channel_id(channel_config.get('id'))
                
                if config_channel_id == normalized_channel_id:
                    keywords = channel_config.get('keywords', [])
                    if keywords:
                        keyword_matches = []
                        for keyword in keywords:
                            if keyword.lower() in message_text_lower:
                                keyword_matches.append(keyword)
                        if keyword_matches:
                            webhook_urls.append(webhook_url)
                            break
                    else:
                        webhook_urls.append(webhook_url)
                        break

        return webhook_urls
    
    def get_all_webhook_urls(self):
        if not self.webhook_config:
            return []
        
        webhook_urls = set()
        for webhook in self.webhook_config.get('webhooks', []):
            webhook_url = webhook.get('url')
            if webhook_url:
                webhook_urls.add(webhook_url)
        return list(webhook_urls)

class TelegramHandler:
    """Handles Telegram client operations and message processing."""
    
    def __init__(self, api_id, api_hash, channel_ids):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel_ids = channel_ids
        self.client = TelegramClient('telecord_session', api_id, api_hash)
    
    async def start(self):
        await self.client.start()
    
    async def get_channel_entity(self, channel_id):
        return await self.client.get_entity(channel_id)
    
    async def resolve_channel_username(self, channel_id):
        try:
            channel = await self.client.get_entity(channel_id)
            if hasattr(channel, 'username') and channel.username:
                return f"@{channel.username}"
            else:
                return str(channel_id)
        except Exception as e:
            return str(channel_id)
    
    async def download_media(self, message):
        try:
            if message.media:
                file_path = await message.download_media()
                logger.info(f"Downloaded media: {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
        return None
    
    def extract_username(self, sender):
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
    
    def get_media_type(self, message):
        if not message.media:
            return None
            
        if isinstance(message.media, MessageMediaPhoto):
            return "Photo"
        elif isinstance(message.media, MessageMediaDocument):
            return "Document (covers many media types)"
        elif isinstance(message.media, MessageMediaWebPage):
            return "Web Page"
        else:
            return "Other Media"
    
    async def get_latest_message(self, channel):
        async for message in self.client.iter_messages(channel, limit=1):
            return message
        return None
    
    async def run_until_disconnected(self):
        await self.client.run_until_disconnected()
    
    def on_new_message(self, callback):
        """Set up new message event handler."""
        @self.client.on(events.NewMessage(chats=self.channel_ids))
        async def new_message_handler(event):
            await callback(event)

class Telecord:
    """Main orchestrator class for Telegram to Discord message forwarding."""
    
    LOG_SEPARATOR_LENGTH = 60
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.api_id, self.api_hash = self.config_manager.get_telegram_credentials()
        self.telegram_channel_ids = self.config_manager.get_channel_ids()
        self.discord_webhook_url = self.config_manager.get_default_webhook()
        self.webhook_config = self.config_manager.get_webhook_config()
        
        self.discord_handler = DiscordHandler(self.discord_webhook_url)
        self.message_router = MessageRouter(self.webhook_config)
        self.telegram_handler = TelegramHandler(self.api_id, self.api_hash, self.telegram_channel_ids)

    def _log_message_info(self, channel_title, username, timestamp, message_text, media_type, is_latest=False):
        prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
        logger.info("=" * self.LOG_SEPARATOR_LENGTH)
        logger.info(f"{prefix} from {channel_title}:")
        logger.info(f"From: {username}")
        logger.info(f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if message_text:
            logger.info(f"Message: {message_text}")
        if media_type:
            logger.info(f"Media: {media_type}")
        logger.info("=" * self.LOG_SEPARATOR_LENGTH)

    async def process_telegram_msg(self, message, channel_title, channel_id=None, is_latest=False):
        username = self.telegram_handler.extract_username(message.sender)
        timestamp = message.date
        message_text = message.text or ""
        media_type = self.telegram_handler.get_media_type(message)
        has_media = media_type is not None
        
        resolved_channel_id = channel_id
        if channel_id and str(channel_id).isdigit():
            resolved_channel_id = await self.telegram_handler.resolve_channel_username(channel_id)
        
        webhook_urls = self.message_router.get_webhooks_for_message(resolved_channel_id, message_text) if resolved_channel_id else []
        
        if not webhook_urls and self.discord_webhook_url:
            webhook_urls = [self.discord_webhook_url]
        
        self._log_message_info(channel_title, username, timestamp, message_text, media_type, is_latest)
        
        if not webhook_urls:
            logger.info(f"No webhook configured for channel {channel_title} ({resolved_channel_id}) or message filtered out")
            return
        
        if has_media and not message_text:
            await self._handle_media_only_msg(message, media_type, channel_title, username, timestamp, is_latest, webhook_urls)
        elif has_media and message_text:
            await self._handle_media_with_caption(message, media_type, channel_title, username, timestamp, message_text, is_latest, webhook_urls)
        elif message_text:
            await self._handle_text_only_msg(channel_title, username, timestamp, message_text, is_latest, webhook_urls)
        else:
            logger.info(f"Empty or unsupported message from {channel_title}")

    async def _handle_media_only_msg(self, message, media_type, channel_title, username, timestamp, is_latest, webhook_urls):
        file_path = await self.telegram_handler.download_media(message)
        if file_path:
            await self.discord_handler.send_media_to_multiple_webhooks(file_path, media_type, channel_title, username, timestamp, is_latest=is_latest, webhook_urls=webhook_urls)
        else:
            self._send_media_fallback_message(channel_title, username, timestamp, media_type, is_latest, webhook_urls=webhook_urls)

    async def _handle_media_with_caption(self, message, media_type, channel_title, username, timestamp, message_text, is_latest, webhook_urls):
        file_path = await self.telegram_handler.download_media(message)
        if file_path:
            await self.discord_handler.send_media_to_multiple_webhooks(file_path, media_type, channel_title, username, timestamp, message_text, is_latest=is_latest, webhook_urls=webhook_urls)
        else:
            self._send_media_fallback_message(channel_title, username, timestamp, media_type, is_latest, message_text, webhook_urls)

    async def _handle_text_only_msg(self, channel_title, username, timestamp, message_text, is_latest, webhook_urls):
        discord_message = self.discord_handler._format_discord_message(
            channel_title, username, timestamp, "Text", message_text, is_latest
        )
        self.discord_handler.send_to_multiple_webhooks(discord_message, webhook_urls)

    def _send_media_fallback_message(self, channel_title, username, timestamp, media_type, is_latest, message_text="", webhook_urls=None):
        content_type = f"{media_type} with caption" if message_text else f"{media_type} (could not download)"
        discord_message = self.discord_handler._format_discord_message(
            channel_title, username, timestamp, content_type, message_text, is_latest
        )
        if webhook_urls:
            self.discord_handler.send_to_multiple_webhooks(discord_message, webhook_urls)
        else:
            self.discord_handler.send_to_discord(discord_message)

    async def start(self):
        await self.telegram_handler.start()
        logger.info("Starting Telecord...")
        logger.info(f"Monitoring channels: {', '.join(self.telegram_channel_ids)}")
        
        self._log_webhook_configuration()
        
        await self.post_latest_message_per_channel()
        await self._setup_message_handler()
        await self.telegram_handler.run_until_disconnected()

    def _log_webhook_configuration(self):
        if self.webhook_config:
            logger.info("Webhook configuration loaded:")
            for webhook in self.webhook_config.get('webhooks', []):
                webhook_name = webhook.get('name', 'unnamed')
                channels = webhook.get('channels', [])
                logger.info(f"  {webhook_name}: {len(channels)} channels configured")
                for channel in channels:
                    channel_id = channel.get('id', 'unknown')
                    keywords = channel.get('keywords', [])
                    if keywords:
                        logger.info(f"    {channel_id} (keywords: {', '.join(keywords)})")
                    else:
                        logger.info(f"    {channel_id} (all messages)")
        elif self.discord_webhook_url:
            logger.info(f"Using default webhook: {self.discord_webhook_url}")

    async def _setup_message_handler(self):
        @self.telegram_handler.client.on(events.NewMessage(chats=self.telegram_channel_ids))
        async def new_message_handler(event):
            await self.handle_new_message(event)

    async def post_latest_message_per_channel(self):
        seen = set()
        for channel_id in self.telegram_channel_ids:
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            try:
                channel = await self.telegram_handler.get_channel_entity(channel_id)
                channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel_id)
                logger.info(f"Processing channel: {channel_id} (resolved as: {channel_title})")
                async for message in self.telegram_handler.client.iter_messages(channel, limit=1):
                    await self.process_telegram_msg(message, channel_title, channel_id, is_latest=True)
            except Exception as e:
                logger.error(f"Error fetching latest message from {channel_id}: {e}")
        
        logger.info("Telecord is now monitoring for new messages.")
        await self._send_startup_message()

    async def _send_startup_message(self):
        startup_message = "**Telecord is now monitoring for new messages.**"
        if self.webhook_config:
            all_webhooks = self.message_router.get_all_webhook_urls()
            self.discord_handler.send_to_multiple_webhooks(startup_message, all_webhooks)
        elif self.discord_webhook_url:
            self.discord_handler.send_to_discord(startup_message)

    async def handle_new_message(self, event):
        try:
            message = event.message
            channel = await event.get_chat()
            channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel.id)
            await self.process_telegram_msg(message, channel_title, channel.id, is_latest=False)
        except Exception as e:
            logger.error(f"Error handling new Telegram message: {e}")

def main():
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
