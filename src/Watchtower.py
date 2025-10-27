import os
import asyncio
import logging
from ConfigManager import ConfigManager
from TelegramHandler import TelegramHandler
from MessageRouter import MessageRouter
from DiscordHandler import DiscordHandler
from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Watchtower:
    """Main application coordinating all components."""
    
    def __init__(self):
        self.config = ConfigManager()
        self.telegram = TelegramHandler(self.config)
        self.router = MessageRouter(self.config)
        self.discord = DiscordHandler()
        
        logger.info("[Watchtower] Initialized")
    
    async def start(self):
        """Start the service."""
        
        await self.telegram.start()
        
        # Setup message handler
        self.telegram.setup_handlers(self._handle_message)
        
        # Log connection proofs
        await self.telegram.fetch_latest_messages()
        
        logger.info("[Watchtower] Now monitoring for new messages...")
        
        await self.telegram.run()
    
    async def _handle_message(self, msg: MessageData, is_latest: bool):
        """Process incoming message."""
        try:
            # If this is a connection proof message, just log it instead of sending to Discord
            if is_latest:
                logger.info(f"\n[Watchtower] CONNECTION ESTABLISHED\n"
                        f"  Channel: {msg.channel_name}\n"
                        f"  Latest message by: {msg.username}\n"
                        f"  Time: {msg.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                return
            
            # Get destinations
            destinations = self.router.get_destinations(msg)
            
            if not destinations:
                logger.info(f"[Watchtower] Message from {msg.channel_name} by {msg.username} has no destinations")
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
                msg.media_path = await self.telegram.download_media(msg)
            
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
                logger.info(f"[Watchtower] Message from {msg.channel_name} by {msg.username} {status} to {dest['name']}")
        
        except Exception as e:
            logger.error(f"[Watchtower] Error processing message from {msg.channel_name} by {msg.username}: {e}", exc_info=True)
        
        # Clean up media file after all destinations have been processed
        if msg.media_path and os.path.exists(msg.media_path):
            try:
                os.remove(msg.media_path)
            except:
                pass

def main():
    try:
        app = Watchtower()
        asyncio.run(app.start())
    except KeyboardInterrupt:
        logger.info("[Watchtower] Stopped by user")
    except Exception as e:
        logger.error(f"[Watchtower] Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()