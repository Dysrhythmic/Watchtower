import logging
import os
import requests
from typing import List, Optional, Dict
from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
                    data = {'username': 'Watchtower', 'content': chunks[0]}
                    response = requests.post(url, files=files, data=data, timeout=15)
                    if response.status_code not in [200, 204]:
                        body = (response.text or "")[:200]
                        logger.error(
                            f"[DiscordHandler] Unsuccessful status code from Discord webhook (media): "
                            f"status={response.status_code}, body={body}"
                        )
                        return False
                    chunks_sent = 1

            # Send text content
            for idx, chunk in enumerate(chunks[chunks_sent:], start=chunks_sent + 1):
                payload = {"username": "Watchtower", "content": chunk}
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code not in [200, 204]:
                    body = (response.text or "")[:200]
                    logger.error(
                            f"[DiscordHandler] Unsuccessful status code from Discord webhook (chunk {idx}/{len(chunks)}): "
                            f"status={response.status_code}, body={body}"
                        )
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
