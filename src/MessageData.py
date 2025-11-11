"""
MessageData - Generic message container for cross-platform message handling

This module defines the MessageData dataclass which serves as a unified representation
of messages from different sources (e.g., Telegram, RSS). It provides a common interface
for message routing, processing, and forwarding operations.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Literal, Any
from datetime import datetime
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_RSS

@dataclass
class MessageData:
    """Generic container for message information from any source.

    Attributes:
        source_type: Platform origin
        channel_id: Unique channel identifier (e.g., username, numeric ID, or RSS URL)
        channel_name: Human-readable channel name
        username: Message sender or source label
        timestamp: Message creation time
        text: Primary message text content
        has_attachments: Whether message contains attachment or not
        attachment_type: Type of attachment (e.g., photo, video, document, etc.)
        attachment_path: Local filesystem path to downloaded attachment
        reply_context: Data related to the message being replied to
        original_message: Original platform-specific message object
        ocr_enabled: Whether OCR processing should be applied or not
        ocr_raw: Extracted text from OCR processing
        metadata: Flexible storage for additional data (rss_link, defanged URLs, etc.)
    """

    source_type: Literal[APP_TYPE_TELEGRAM, APP_TYPE_RSS] = APP_TYPE_TELEGRAM

    channel_id: str = ""
    channel_name: str = ""
    username: str = ""
    timestamp: datetime = None

    text: str = ""

    has_attachments: bool = False
    attachment_type: Optional[str] = None
    attachment_path: Optional[str] = None

    reply_context: Optional[Dict] = None

    original_message: Optional[object] = None

    ocr_enabled: bool = False
    ocr_raw: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)
