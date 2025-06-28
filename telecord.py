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

def format_message_content(channel_title, username, timestamp, content_type, message_text="", is_latest=False, reply_context=None, matched_keywords=None):
    """Formats message content for Discord webhooks.
    
    The 'is_latest' flag changes the prefix to indicate this is the most recent
    message when establishing initial connection to a channel.
    
    The 'reply_context' parameter includes information about what message this is replying to.
    
    The 'matched_keywords' parameter includes the keywords that triggered this message to be sent.
    """
    prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
    content_parts = [
        f"**{prefix.lower().title()} from channel:** {channel_title}",
        f"**By:** {username}",
        f"**Time:** {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Content:** {content_type}"
    ]
    
    # Add matched keywords if available
    if matched_keywords:
        keywords_text = ", ".join(matched_keywords)
        content_parts.append(f"**Matched Keywords:** {keywords_text}")
    
    # Add reply context if available
    if reply_context:
        reply_author = reply_context.get('author', 'Unknown')
        reply_text = reply_context.get('text', '')
        reply_time = reply_context.get('time', '')
        
        reply_info = f"**Replying to:** {reply_author}"
        if reply_time:
            reply_info += f" ({reply_time})"
        if reply_text:
            # Truncate long reply text to keep messages readable
            truncated_reply = reply_text[:100] + "..." if len(reply_text) > 100 else reply_text
            reply_info += f"\n**Original message:** {truncated_reply}"
        
        content_parts.append(reply_info)
    
    if message_text:
        content_parts.append(f"**Message:**\n{message_text}")
    
    return "\n".join(content_parts)

class ConfigManager:
    """Handles all configuration loading and validation.
    
    Supports two routing modes:
    - Simple: Single webhook for all messages (DISCORD_WEBHOOK_URL)
    - Advanced: Multiple webhooks with channel specific routing and keyword filtering
    
    Environment variables are resolved at runtime to keep sensitive webhook URLs
    out of configuration files.
    """
    
    def __init__(self):
        # Core Telegram API credentials- required for all operations
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_channel_ids = os.getenv('TELEGRAM_CHANNEL_IDS', '').split(',')
        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        self.config_file = os.getenv('WEBHOOK_CONFIG_FILE', 'webhook_config.json')
        
        # Only load advanced config if no default webhook is provided
        # This prevents conflicts between simple and advanced routing modes
        if not self.discord_webhook_url:
            self.webhook_config = self._load_webhook_config()
        else:
            self.webhook_config = None
            logger.info("Using simple routing mode with default webhook")
        
        self._validate_config()
    
    def _load_webhook_config(self):
        """Loads JSON configuration file for advanced routing.
        
        Returns None if file doesn't exist, allowing fallback to
        simple routing mode. This prevents startup failures when users
        haven't set up advanced configuration yet.
        """
        if not os.path.exists(self.config_file):
            logger.info(f"Webhook config file {self.config_file} not found, using default webhook")
            return None
            
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded webhook configuration from {self.config_file}")
                
                # Replace environment variable references with actual webhook URLs
                self._resolve_webhook_urls(config)
                
                return config
        except Exception as e:
            logger.error(f"Error loading webhook config from {self.config_file}: {e}")
            return None
    
    def _resolve_webhook_urls(self, config):
        """Resolves environment variable references to actual webhook URLs.
        
        This allows storing sensitive webhook URLs in environment variables
        while keeping the routing configuration in readable JSON files.
        Invalid or missing environment variables are filtered out to prevent
        runtime errors.
        """
        valid_webhooks = []
        
        for webhook in config.get('webhooks', []):
            env_key = webhook.get('env_key')
            if env_key:
                webhook_url = os.getenv(env_key)
                if webhook_url:
                    webhook['url'] = webhook_url
                    webhook.pop('env_key', None)  # Clean up config after resolution
                    valid_webhooks.append(webhook)
                    logger.info(f"Resolved {env_key} to webhook URL")
                else:
                    # Only warn if we're in advanced routing mode
                    if not self.discord_webhook_url:
                        logger.warning(f"Environment variable {env_key} not found, skipping webhook")
            else:
                # Webhook already has a direct URL, keep it as is
                valid_webhooks.append(webhook)
        
        config['webhooks'] = valid_webhooks
    
    def _validate_config(self):
        """Validates that all required configuration is present.
        
        Ensures at least one routing method is available (simple or advanced)
        and logs which mode is being used for clarity.
        """
        if not all([self.api_id, self.api_hash, self.telegram_channel_ids]):
            raise ValueError("Missing required environment variables. Please check TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_CHANNEL_IDS")
        
        if not self.discord_webhook_url and not self.webhook_config:
            raise ValueError(f"Either DISCORD_WEBHOOK_URL or {self.config_file} must be provided")
        
        # Log routing mode for debugging and user awareness
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

class DiscordHandler:
    """Handles all Discord webhook operations.
    
    Manages message sending with automatic chunking for long messages (Discord's
    2000 character limit) and supports both single and multiple webhook routing.
    Includes retry logic and error handling for network issues.
    """
    
    DISCORD_MAX_LENGTH = 2000  # Discord's message character limit
    DISCORD_SUCCESS_CODES = [200, 204]  # HTTP status codes indicating success
    
    def __init__(self, default_webhook_url=None):
        self.default_webhook_url = default_webhook_url
    
    def send_to_multiple_webhooks(self, message, webhook_urls):
        """Sends the same message to multiple Discord webhooks.
        
        Continues sending to remaining webhooks even if some fail, ensuring
        maximum message delivery. Returns False only if ALL webhooks fail.
        """
        if not webhook_urls:
            logger.warning("No webhook URLs provided")
            return False
            
        success = True
        for webhook_url in webhook_urls:
            if not self._send_message_to_webhook(message, webhook_url):
                success = False
        return success
    
    def _send_message_to_webhook(self, message, webhook_url):
        """Sends a message to a specific webhook.
        
        Automatically chunks messages that exceed Discord's character limit
        to prevent truncation and ensure complete message delivery.
        """
        if len(message) <= self.DISCORD_MAX_LENGTH:
            # Single message fits within limit
            payload = {
                "content": message,
                "username": "Telecord"
            }
            return self._make_discord_request(payload, "Message", webhook_url)
        else:
            # Message needs to be chunked
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
    
    def _make_discord_request(self, payload, description, webhook_url=None):
        """Makes HTTP POST request to Discord webhook with error handling.
        
        Uses a 10 second timeout to prevent hanging on network issues and
        provides logging for debugging webhook delivery problems.
        """
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
    
    async def send_media_to_discord(self, file_path, media_type, channel_title, username, timestamp, message_text="", is_latest=False, webhook_url=None, cleanup_after=True, reply_context=None, matched_keywords=None):
        """Uploads media files to Discord with formatted message caption.
        
        Uses multipart form data to upload files directly to Discord webhooks,
        which is more efficient than downloading and reuploading. Includes
        automatic cleanup of temporary files to prevent disk space issues.
        """
        target_webhook = webhook_url or self.default_webhook_url
        if not target_webhook:
            logger.error(f"No webhook URL available for media ({media_type})")
            return False
            
        try:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                
                full_content = format_message_content(
                    channel_title, username, timestamp, media_type, message_text, is_latest, reply_context, matched_keywords
                )
                
                data = {
                    'username': 'Telecord',
                    'content': full_content
                }
                response = requests.post(
                    target_webhook,
                    files=files,
                    data=data,
                    timeout=30  # Longer timeout for file uploads
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
            # Only cleanup if explicitly requested (for single webhook sends)
            if cleanup_after:
                self._cleanup_temp_file(file_path)
    
    def _cleanup_temp_file(self, file_path):
        """Removes temporary media files to prevent disk space accumulation.
        
        Called after every media upload attempt, regardless of success/failure,
        to ensure temporary files don't accumulate over time.
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")
    
    async def send_media_to_multiple_webhooks(self, file_path, media_type, channel_title, username, timestamp, message_text="", is_latest=False, webhook_urls=None, reply_context=None, matched_keywords=None):
        """Sends the same media file to multiple Discord webhooks.
        
        Downloads the file once and uploads it to each webhook.
        """
        if not webhook_urls:
            logger.warning("No webhook URLs provided for media")
            return False
            
        success = True
        for webhook_url in webhook_urls:
            # Don't cleanup after each webhook, only after all are processed
            if not await self.send_media_to_discord(file_path, media_type, channel_title, username, timestamp, message_text, is_latest, webhook_url, cleanup_after=False, reply_context=reply_context, matched_keywords=matched_keywords):
                success = False
        
        # Cleanup the file after all webhooks have been processed
        self._cleanup_temp_file(file_path)
        return success

class MessageRouter:
    """Handles message routing and filtering logic.
    
    Matches incoming messages to appropriate Discord webhooks based on channel
    configuration and optional keyword filters. Supports advanced routing scenarios
    where one channel can send to multiple webhooks with different filters.
    """
    
    def __init__(self, webhook_config):
        self.webhook_config = webhook_config
    
    def _normalize_channel_id(self, channel_id):
        """Normalizes channel identifiers for consistent matching.
        
        Converts all channel IDs to strings to handle both numeric IDs from
        Telegram API and @username formats from configuration files.
        """
        if not channel_id:
            return channel_id
            
        channel_id_str = str(channel_id)
        
        return channel_id_str
    
    def get_webhooks_for_message(self, channel_id, message_text=""):
        """Determines which webhooks should receive a given message.
        
        Matches channel ID first, then applies keyword filtering if configured.
        Returns a tuple of (webhook_urls, matched_keywords) where webhook_urls is a list
        of webhook URLs and matched_keywords is a list of keywords that matched.
        Returns empty lists if no webhooks match, allowing fallback to default
        webhook in the main processing logic.
        """
        if not self.webhook_config:
            return [], []
        
        webhook_urls = set()  # Use set to prevent duplicates
        matched_keywords = set()  # Use set to prevent duplicates
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
                        # Check if any keywords match the message content
                        keyword_matches = []
                        for keyword in keywords:
                            if keyword.lower() in message_text_lower:
                                keyword_matches.append(keyword)
                        if keyword_matches:
                            webhook_urls.add(webhook_url)  # Use add() for set
                            matched_keywords.update(keyword_matches)  # Use update() for set
                            logger.info(f"Keyword match found for channel {channel_id}: {keyword_matches} -> webhook added")
                            break  # Found match for this webhook, move to next
                    else:
                        # No keywords specified, send all messages from this channel
                        webhook_urls.add(webhook_url)  # Use add() for set
                        break  # Found match for this webhook, move to next

        # Convert sets back to lists for return
        webhook_urls_list = list(webhook_urls)
        matched_keywords_list = list(matched_keywords)
        
        return webhook_urls_list, matched_keywords_list
    
    def get_all_webhook_urls(self):
        """Returns all configured webhook URLs for startup notifications.
        
        Used to send connection status messages to all webhooks when
        Telecord starts up, ensuring all destinations are aware of the
        service status.
        """
        if not self.webhook_config:
            return []
        
        webhook_urls = set()
        for webhook in self.webhook_config.get('webhooks', []):
            webhook_url = webhook.get('url')
            if webhook_url:
                webhook_urls.add(webhook_url)
        return list(webhook_urls)

class TelegramHandler:
    """Handles Telegram client operations and message processing.
    
    Manages the Telegram client connection, handles message events, and provides
    utilities for extracting user information and downloading media files.
    Includes error handling for network issues and API limitations.
    """
    
    def __init__(self, api_id, api_hash, channel_ids):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel_ids = channel_ids
        self.client = TelegramClient('telecord_session', api_id, api_hash)
    
    async def start(self):
        """Initializes the Telegram client connection.
        
        Creates session file for persistent authentication, reducing
        the need for frequent reauthentication on restarts.
        """
        await self.client.start()
    
    async def get_channel_entity(self, channel_id):
        """Retrieves channel information from Telegram.
        
        Used for getting channel titles and metadata when processing
        messages or establishing initial connections.
        """
        # Convert numeric channel IDs to integers for proper Telethon handling
        if isinstance(channel_id, str) and channel_id.startswith('-') and channel_id[1:].isdigit():
            channel_id = int(channel_id)
        
        return await self.client.get_entity(channel_id)
    
    async def resolve_channel_username(self, channel_id):
        """Converts numeric channel IDs to @username format for configuration matching.
        
        Telegram sometimes sends numeric IDs instead of usernames, especially for
        private channels. This method resolves them to the standard @username format
        used in configuration files for consistent routing.
        """
        try:
            channel = await self.client.get_entity(channel_id)
            if hasattr(channel, 'username') and channel.username:
                return f"@{channel.username}"
            else:
                return str(channel_id)
        except Exception as e:
            return str(channel_id)
    
    async def download_media(self, message):
        """Downloads media files from Telegram messages.
        
        Creates temporary files that are automatically cleaned up after
        Discord upload. Handles various media types including photos,
        documents, videos, and audio files.
        """
        try:
            if message.media:
                file_path = await message.download_media()
                logger.info(f"Downloaded media: {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
        return None
    
    def extract_username(self, sender):
        """Extracts human readable username from Telegram sender.
        
        Prioritizes @username format for consistency, falls back to
        first/last name combination, and provides "Unknown" for anonymous
        or deleted accounts.
        """
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
        """Identifies the type of media in a Telegram message.
        
        Categorizes media for better Discord formatting and user
        understanding. Handles the most common media types while
        providing fallback for unknown formats.
        """
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
    
    async def get_reply_context(self, message):
        """Extracts reply context from a Telegram message.
        
        If the message is a reply to another message, retrieves information
        about the original message including author, text, and timestamp.
        Returns None if the message is not a reply.
        """
        try:
            if hasattr(message, 'reply_to') and message.reply_to:
                # Get the replied-to message
                replied_message = await self.client.get_messages(
                    message.chat_id, 
                    ids=message.reply_to.reply_to_msg_id
                )
                
                if replied_message:
                    reply_author = self.extract_username(replied_message.sender)
                    reply_text = replied_message.text or ""
                    reply_time = replied_message.date.strftime('%Y-%m-%d %H:%M:%S UTC') if replied_message.date else ""
                    
                    return {
                        'author': reply_author,
                        'text': reply_text,
                        'time': reply_time
                    }
        except Exception as e:
            logger.error(f"Error getting reply context: {e}")
        
        return None
    
    async def get_latest_message(self, channel):
        """Retrieves the most recent message from a channel.
        
        Used during startup to establish connection status and provide
        immediate feedback that the channel is being monitored.
        """
        async for message in self.client.iter_messages(channel, limit=1):
            return message
        return None
    
    async def run_until_disconnected(self):
        """Maintains the Telegram client connection indefinitely.
        
        Keeps the bot online and listening for new messages until
        manually stopped or network issues occur.
        """
        await self.client.run_until_disconnected()

class Telecord:
    """Main orchestrator class for Telegram to Discord message forwarding.
    
    Coordinates config, routing, Discord, and Telegram components to provide
    message forwarding with support for both simple and advanced routing modes.
    """
    
    LOG_SEPARATOR_LENGTH = 60
    
    def __init__(self):
        # Initialize all components with dependency injection pattern
        self.config_manager = ConfigManager()
        self.api_id, self.api_hash = self.config_manager.get_telegram_credentials()
        self.telegram_channel_ids = self.config_manager.get_channel_ids()
        self.discord_webhook_url = self.config_manager.get_default_webhook()
        self.webhook_config = self.config_manager.get_webhook_config()
        
        # Create handlers with appropriate dependencies
        self.discord_handler = DiscordHandler(self.discord_webhook_url)
        self.message_router = MessageRouter(self.webhook_config)
        self.telegram_handler = TelegramHandler(self.api_id, self.api_hash, self.telegram_channel_ids)

    def _log_message_info(self, channel_title, username, timestamp, message_text, media_type, is_latest=False):
        """Logs message details for debugging and monitoring.
        
        Provides consistent logging format for all messages, making it easier
        to track message flow and diagnose routing issues.
        """
        prefix = "CONNECTION ESTABLISHED - Latest message" if is_latest else "New message"
        logger.info("=" * self.LOG_SEPARATOR_LENGTH)
        logger.info(f"{prefix} from {channel_title}:")
        logger.info(f"By: {username}")
        logger.info(f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if message_text:
            logger.info(f"Message: {message_text}")
        if media_type:
            logger.info(f"Media: {media_type}")
        logger.info("=" * self.LOG_SEPARATOR_LENGTH)

    async def process_telegram_msg(self, message, channel_title, channel_id=None, is_latest=False):
        """Main message processing pipeline.
        
        Handles the complete flow from message reception to Discord delivery:
        1. Extract message metadata (sender, timestamp, content)
        2. Resolve channel ID for routing (numeric to @username)
        3. Determine target webhooks based on configuration
        4. Route message based on content type (text/media)
        5. Handle fallback to default webhook if no matches found
        
        Returns True if the message was processed and sent to Discord, False if filtered out.
        """
        username = self.telegram_handler.extract_username(message.sender)
        timestamp = message.date
        message_text = message.text or ""
        media_type = self.telegram_handler.get_media_type(message)
        has_media = media_type is not None
        
        # Get reply context if this message is a reply
        reply_context = await self.telegram_handler.get_reply_context(message)
        
        # Resolve numeric channel IDs to @username format for config matching
        resolved_channel_id = channel_id
        if channel_id and str(channel_id).isdigit():
            resolved_channel_id = await self.telegram_handler.resolve_channel_username(channel_id)
        
        # Get target webhooks based on channel and keyword filtering
        webhook_urls, matched_keywords = self.message_router.get_webhooks_for_message(resolved_channel_id, message_text) if resolved_channel_id else ([], [])
        
        # Log the filtering results
        if resolved_channel_id:
            if webhook_urls:
                logger.info(f"Keyword filtering for channel {resolved_channel_id}: {len(webhook_urls)} webhook(s) matched")
        else:
            logger.warning(f"No resolved channel ID for {channel_id}, skipping keyword filtering")
        
        # Fallback to default webhook if no advanced routing matches
        if not webhook_urls and self.discord_webhook_url:
            webhook_urls = [self.discord_webhook_url]
            logger.info(f"Using fallback to default webhook for channel {resolved_channel_id}")
        
        if not webhook_urls:
            return False
        
        # Only log messages that are actually being processed
        self._log_message_info(channel_title, username, timestamp, message_text, media_type, is_latest)
        
        # Route message based on content type
        if has_media and not message_text:
            await self._handle_media_msg(message, media_type, channel_title, username, timestamp, is_latest, webhook_urls, reply_context=reply_context, matched_keywords=matched_keywords)
        elif has_media and message_text:
            await self._handle_media_msg(message, media_type, channel_title, username, timestamp, is_latest, webhook_urls, message_text, reply_context, matched_keywords)
        elif message_text:
            await self._handle_text_only_msg(channel_title, username, timestamp, message_text, is_latest, webhook_urls, reply_context, matched_keywords)
        else:
            logger.info(f"Empty or unsupported message from {channel_title}")
        
        return True

    async def _handle_media_msg(self, message, media_type, channel_title, username, timestamp, is_latest, webhook_urls, message_text="", reply_context=None, matched_keywords=None):
        """Handles media messages (with or without captions).
        
        Downloads media file once and uploads to all target webhooks,
        providing fallback text message if download fails.
        """
        file_path = await self.telegram_handler.download_media(message)
        if file_path:
            await self.discord_handler.send_media_to_multiple_webhooks(file_path, media_type, channel_title, username, timestamp, message_text, is_latest=is_latest, webhook_urls=webhook_urls, reply_context=reply_context, matched_keywords=matched_keywords)
        else:
            self._send_media_fallback_message(channel_title, username, timestamp, media_type, is_latest, message_text, webhook_urls, matched_keywords)

    async def _handle_text_only_msg(self, channel_title, username, timestamp, message_text, is_latest, webhook_urls, reply_context=None, matched_keywords=None):
        """Handles text-only messages.
        
        Formats message with metadata and sends to all target webhooks
        using the unified message formatting utility.
        """
        discord_message = format_message_content(
            channel_title, username, timestamp, "Text", message_text, is_latest, reply_context, matched_keywords
        )
        self.discord_handler.send_to_multiple_webhooks(discord_message, webhook_urls)

    def _send_media_fallback_message(self, channel_title, username, timestamp, media_type, is_latest, message_text="", webhook_urls=None, matched_keywords=None):
        """Sends message when media download fails.
        
        Provides feedback to the user about media content even when the actual
        file cannot be downloaded or uploaded to Discord.
        """
        content_type = f"{media_type} with caption" if message_text else f"{media_type} (could not download)"
        discord_message = format_message_content(
            channel_title, username, timestamp, content_type, message_text, is_latest, matched_keywords=matched_keywords
        )
        if webhook_urls:
            self.discord_handler.send_to_multiple_webhooks(discord_message, webhook_urls)
        else:
            self.discord_handler._send_message_to_webhook(discord_message, self.discord_webhook_url)

    async def start(self):
        """Initializes and starts the Telecord service.
        
        Establishes Telegram connection, posts latest messages to establish
        monitoring status, sets up event handlers, and begins listening
        for new messages indefinitely.
        """
        await self.telegram_handler.start()
        logger.info("Starting Telecord...")
        logger.info(f"Monitoring channels: {', '.join(self.telegram_channel_ids)}")
        
        self._log_webhook_configuration()
        
        # Post latest message from each channel to establish connection status
        await self.post_latest_message_per_channel()
        await self._setup_message_handler()
        await self.telegram_handler.run_until_disconnected()

    def _log_webhook_configuration(self):
        """Logs the current webhook configuration for debugging.
        
        Shows which webhooks are configured, which channels they monitor,
        and any keyword filters applied. Helps users verify their setup.
        """
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
        """Configures Telegram event handler for new messages.
        
        Sets up the callback that will be triggered whenever a new message
        is received from any monitored channel.
        """
        # Convert negative channel IDs to integers for proper Telethon handling
        processed_channel_ids = []
        for channel_id in self.telegram_channel_ids:
            if isinstance(channel_id, str) and channel_id.startswith('-') and channel_id[1:].isdigit():
                processed_channel_ids.append(int(channel_id))
            else:
                processed_channel_ids.append(channel_id)
        
        @self.telegram_handler.client.on(events.NewMessage(chats=processed_channel_ids))
        async def new_message_handler(event):
            await self.handle_new_message(event)

    async def post_latest_message_per_channel(self):
        """Posts the most recent message from each monitored channel.
        
        Establishes connection status and provides immediate feedback that
        each channel is being monitored. Prevents duplicate processing by
        tracking already seen channels.
        """
        seen = set()
        for channel_id in self.telegram_channel_ids:
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            try:
                channel = await self.telegram_handler.get_channel_entity(channel_id)
                channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel_id)
                logger.info(f"Processing channel: {channel_id} (resolved as: {channel_title})")
                
                # Track if we found and processed a message
                message_processed = False
                async for message in self.telegram_handler.client.iter_messages(channel, limit=1):
                    was_sent = await self.process_telegram_msg(message, channel_title, channel_id, is_latest=True)
                    if not was_sent:
                        logger.info(f"Latest message from {channel_title} filtered out (no keyword matches)")
                    message_processed = True
                    break
                
                if not message_processed:
                    logger.info(f"No messages found in channel {channel_title}")
                    
            except Exception as e:
                logger.error(f"Error fetching latest message from {channel_id}: {e}")
        
        logger.info("Telecord is now monitoring for new messages.")
        await self._send_startup_message()

    async def _send_startup_message(self):
        """Sends startup notification to all configured webhooks.
        
        Informs all destinations that Telecord is now online and monitoring,
        providing immediate feedback about service status.
        """
        startup_message = "**Telecord is now monitoring for new messages.**"
        if self.webhook_config:
            all_webhooks = self.message_router.get_all_webhook_urls()
            self.discord_handler.send_to_multiple_webhooks(startup_message, all_webhooks)
        elif self.discord_webhook_url:
            self.discord_handler._send_message_to_webhook(startup_message, self.discord_webhook_url)

    async def handle_new_message(self, event):
        """Event handler for new Telegram messages.
        
        Extracts message and channel information from the Telegram event
        and passes it to the main processing pipeline.
        """
        try:
            message = event.message
            channel = await event.get_chat()
            channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel.id)
            await self.process_telegram_msg(message, channel_title, channel.id, is_latest=False)
        except Exception as e:
            logger.error(f"Error handling new Telegram message: {e}")

def main():
    """Application entry point with error handling.
    
    Creates Telecord instance and runs the main service loop with
    graceful handling of keyboard interrupts and fatal errors.
    """
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
