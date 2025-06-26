import os
import asyncio
import logging
import requests
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Telecord:
    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.telegram_channel_ids = os.getenv('TELEGRAM_CHANNEL_ID', '').split(',')
        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

        if not all([self.api_id, self.api_hash, self.telegram_channel_ids, self.discord_webhook_url]):
            raise ValueError("Missing required environment variables. Please check TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHANNEL_ID, and DISCORD_WEBHOOK_URL")

        self.client = TelegramClient('telecord_session', self.api_id, self.api_hash)

    def send_to_discord(self, message):
        """Send message to Discord using webhook, splitting into 2000-char chunks if needed."""
        max_length = 2000
        success = True
        chunks = [message[i:i+max_length] for i in range(0, len(message), max_length)]
        for idx, chunk in enumerate(chunks):
            payload = {
                "content": chunk,
                "username": "Telecord"
            }
            try:
                response = requests.post(
                    self.discord_webhook_url,
                    json=payload,
                    timeout=10
                )
                if response.status_code == 204:
                    logger.info(f"Message chunk {idx+1}/{len(chunks)} sent to Discord successfully")
                else:
                    logger.error(f"Failed to send chunk {idx+1}/{len(chunks)} to Discord: {response.status_code} - {response.text}")
                    success = False
            except Exception as e:
                logger.error(f"Error sending chunk {idx+1}/{len(chunks)} to Discord: {e}")
                success = False
        return success

    async def post_latest_message_per_channel(self):
        """Post the most recent message from each unique channel, then send monitoring notice."""
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
                    if message.text:
                        username = "Unknown"
                        if message.sender:
                            sender = message.sender
                            if hasattr(sender, 'username') and sender.username:
                                username = f"@{sender.username}"
                            elif hasattr(sender, 'first_name') and sender.first_name:
                                username = sender.first_name
                                if hasattr(sender, 'last_name') and sender.last_name:
                                    username += f" {sender.last_name}"
                        timestamp = message.date
                        message_text = message.text
                        logger.info("=" * 60)
                        logger.info(f"CONNECTION ESTABLISHED - Latest message from {channel_title}:")
                        logger.info(f"From: {username}")
                        logger.info(f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                        logger.info(f"Message: {message_text}")
                        logger.info("=" * 60)
                        discord_message = (
                            f"**Latest message from channel:** {channel_title}\n"
                            f"**From:** {username}\n"
                            f"**Time:** {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                            f"**Message:**\n{message_text}"
                        )
                        self.send_to_discord(discord_message)
            except Exception as e:
                logger.error(f"Error fetching latest message from {channel_id}: {e}")
        logger.info("Telecord is now monitoring for new messages.")
        self.send_to_discord("**Telecord is now monitoring for new messages.**")

    async def handle_new_message(self, event):
        try:
            message = event.message
            if not message.text:
                return
            channel = await event.get_chat()
            channel_title = getattr(channel, 'title', None) or getattr(channel, 'username', channel.id)
            username = "Unknown"
            if message.sender:
                sender = message.sender
                if hasattr(sender, 'username') and sender.username:
                    username = f"@{sender.username}"
                elif hasattr(sender, 'first_name') and sender.first_name:
                    username = sender.first_name
                    if hasattr(sender, 'last_name') and sender.last_name:
                        username += f" {sender.last_name}"
            timestamp = message.date
            message_text = message.text
            logger.info(f"New message from {channel_title} by {username} at {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            logger.info(f"Message: {message_text}")
            discord_message = (
                f"**New message from channel:** {channel_title}\n"
                f"**From:** {username}\n"
                f"**Time:** {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"**Message:**\n{message_text}"
            )
            self.send_to_discord(discord_message)
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