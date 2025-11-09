"""
MessageData - Generic message container for cross-platform message handling

This module defines the MessageData dataclass which serves as a unified representation
of messages from different sources (Telegram, RSS). It provides a common interface
for message routing, processing, and forwarding operations.

Key Features:
- Source-agnostic design (works with Telegram, RSS, or future sources)
- OCR integration support for image text extraction
- Metadata extensibility via flexible metadata dict
- Media attachment tracking
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Literal, Any
from datetime import datetime
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS

@dataclass
class MessageData:
    """Generic container for message information from any source.

    Attributes:
        source_type: Platform origin ("telegram" or "rss")
        channel_id: Unique channel identifier (username, numeric ID, or RSS URL)
        channel_name: Human-readable channel name
        username: Message sender or source label
        timestamp: Message creation time
        text: Primary message text content
        has_media: Whether message contains media attachment
        media_type: Type of media (photo, video, document, etc.)
        media_path: Local filesystem path to downloaded media
        reply_context: Optional reply-to information (Telegram only)
        original_message: Original platform-specific message object
        ocr_enabled: Whether OCR processing should be applied
        ocr_raw: Extracted text from OCR processing
        metadata: Flexible storage for additional data (rss_link, defanged URLs, etc.)
    """

    # Source identity
    source_type: Literal["telegram", "rss"] = APP_TYPE_TELEGRAM

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
