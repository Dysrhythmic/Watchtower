from dataclasses import dataclass, field
from typing import Optional, Dict, Literal, Any
from datetime import datetime

@dataclass
class MessageData:
    """Generic container for message information from any source"""

    # Source identity
    source_type: Literal["telegram", "rss"] = "telegram"

    # Origin / display
    channel_id: str = ""
    channel_name: str = ""
    username: str = ""  # sender or logical source label
    timestamp: datetime = None

    # Primary text
    text: str = ""

    # Media
    has_media: bool = False
    media_type: Optional[str] = None
    media_path: Optional[str] = None

    # Optional reply context (Telegram)
    reply_context: Optional[Dict] = None

    # The original Telegram message object when source_type == "telegram"
    original_message: Optional[object] = None

    # OCR integration
    ocr_enabled: bool = False              # whether OCR should be applied
    ocr_raw: Optional[str] = None          # full OCR text (used for keyword matching and output)

    # Flexible metadata (e.g., rss_link, ocr fields, defanged URLs)
    metadata: Dict[str, Any] = field(default_factory=dict)
