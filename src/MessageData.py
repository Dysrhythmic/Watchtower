from dataclasses import dataclass
from typing import Optional, Dict

@dataclass
class MessageData:
    """Container for extracted message information from Telegram."""
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
