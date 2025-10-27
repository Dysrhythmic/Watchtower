import logging
from typing import List, Dict
from ConfigManager import ConfigManager
from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

        # Determine if this channel appears anywhere in config
        channel_is_configured = False
        for webhook in self.config.webhooks:
            for channel in webhook.get('channels', []):
                if self._channel_matches(msg.channel_id, msg.channel_name, channel['id']):
                    channel_is_configured = True
                    break
            if channel_is_configured:
                break

        # If the channel isn't configured, log and return empty
        if not channel_is_configured:
            logger.info(
                f"[MessageRouter] No configured matches for channel {msg.channel_name} ({msg.channel_id})"
            )
            return destinations  # []

        # Otherwise collect destinations
        for webhook in self.config.webhooks:
            # Find matching channel config for this webhook
            channel_config = None
            for channel in webhook['channels']:
                if self._channel_matches(msg.channel_id, msg.channel_name, channel['id']):
                    channel_config = channel
                    break

            if not channel_config:
                continue

            # Check keywords
            keywords = channel_config.get('keywords')
            if not keywords:
                # No keywords field -> forward all
                destinations.append({
                    'name': webhook['name'],
                    'url': webhook['url'],
                    'keywords': [],
                    'restricted_mode': channel_config.get('restricted_mode', False),
                    'parser': channel_config.get('parser', 0)
                })
            elif keywords and msg.text:
                # Keyword substring match (case-insensitive)
                matched = [kw for kw in keywords if kw.lower() in msg.text.lower()]
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
