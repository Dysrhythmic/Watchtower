import os
import asyncio
import logging
import requests
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Telecord:
    DISCORD_MAX_LENGTH = 2000
    DISCORD_SUCCESS_CODES = [200, 204]
    LOG_SEPARATOR_LENGTH = 60
    
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_channel_ids = os.getenv('TELEGRAM_CHANNEL_ID', '').split(',')
        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

        if not all([self.api_id, self.api_hash, self.telegram_channel_ids, self.discord_webhook_url]):
            raise ValueError("Missing required environment variables. Please check TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHANNEL_ID, and DISCORD_WEBHOOK_URL")

        self.client = TelegramClient('telecord_session', self.api_id, self.api_hash)

    def _extract_username(self, sender):
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

    def _get_media_type(self, message):
        if not message.media:
            return None
            
        if isinstance(message.media, MessageMediaPhoto):
            return "Image"
        elif isinstance(message.media, MessageMediaDocument):
            return "Document (or uncompressed image)"
        elif isinstance(message.media, MessageMediaWebPage):
            return "Web Page"
        else:
            return "Other Media"

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

    def _make_discord_request(self, payload, description):
        try:
            response = requests.post(
                self.discord_webhook_url,
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

    async def download_media(self, message):
        try:
            if message.media:
                file_path = await message.download_media()
                logger.info(f"Downloaded media: {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
        return None

    async def send_media_to_discord(self, file_path, media_type, channel_title, username, timestamp, message_text="", is_latest=False):
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
                    self.discord_webhook_url,
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

    def _cleanup_temp_file(self, file_path):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {e}")

    async def process_telegram_msg(self, message, channel_title, is_latest=False):
        username = self._extract_username(message.sender)
        timestamp = message.date
        message_text = message.text or ""
        media_type = self._get_media_type(message)
        has_media = media_type is not None
        
        self._log_message_info(channel_title, username, timestamp, message_text, media_type, is_latest)
        
        if has_media and not message_text:
            await self._handle_media_only_msg(message, media_type, channel_title, username, timestamp, is_latest)
        elif has_media and message_text:
            await self._handle_media_with_caption(message, media_type, channel_title, username, timestamp, message_text, is_latest)
        elif message_text:
            await self._handle_text_only_msg(channel_title, username, timestamp, message_text, is_latest)
        else:
            logger.info(f"Empty or unsupported message from {channel_title}")

    async def _handle_media_only_msg(self, message, media_type, channel_title, username, timestamp, is_latest):
        file_path = await self.download_media(message)
        if file_path:
            await self.send_media_to_discord(file_path, media_type, channel_title, username, timestamp, is_latest=is_latest)
        else:
            self._send_media_fallback_message(channel_title, username, timestamp, media_type, is_latest)

    async def _handle_media_with_caption(self, message, media_type, channel_title, username, timestamp, message_text, is_latest):
        file_path = await self.download_media(message)
        if file_path:
            await self.send_media_to_discord(file_path, media_type, channel_title, username, timestamp, message_text, is_latest=is_latest)
        else:
            self._send_media_fallback_message(channel_title, username, timestamp, media_type, is_latest, message_text)

    async def _handle_text_only_msg(self, channel_title, username, timestamp, message_text, is_latest):
        discord_message = self._format_discord_message(
            channel_title, username, timestamp, "Text", message_text, is_latest
        )
        self.send_to_discord(discord_message)

    def _send_media_fallback_message(self, channel_title, username, timestamp, media_type, is_latest, message_text=""):
        content_type = f"{media_type} with caption" if message_text else f"{media_type} (could not download)"
        discord_message = self._format_discord_message(
            channel_title, username, timestamp, content_type, message_text, is_latest
        )
        self.send_to_discord(discord_message)

    async def post_latest_message_per_channel(self):
        seen = set()
        for channel_id in self.telegram_channel_ids:
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            try:
                channel = await self.client.get_entity(channel_id)
                channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel_id)
                logger.info(f"Processing channel: {channel_id} (resolved as: {channel_title})")
                async for message in self.client.iter_messages(channel, limit=1):
                    await self.process_telegram_msg(message, channel_title, is_latest=True)
            except Exception as e:
                logger.error(f"Error fetching latest message from {channel_id}: {e}")
        logger.info("Telecord is now monitoring for new messages.")
        self.send_to_discord("**Telecord is now monitoring for new messages.**")

    async def handle_new_message(self, event):
        try:
            message = event.message
            channel = await event.get_chat()
            channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel.id)
            await self.process_telegram_msg(message, channel_title, is_latest=False)
        except Exception as e:
            logger.error(f"Error handling new Telegram message: {e}")

    async def start(self):
        await self.client.start()
        logger.info("Starting Telecord...")
        logger.info(f"Monitoring channels: {', '.join(self.telegram_channel_ids)}")
        logger.info(f"Forwarding to Discord webhook")
        await self.post_latest_message_per_channel()

        @self.client.on(events.NewMessage(chats=self.telegram_channel_ids))
        async def new_message_handler(event):
            await self.handle_new_message(event)

        await self.client.run_until_disconnected()

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