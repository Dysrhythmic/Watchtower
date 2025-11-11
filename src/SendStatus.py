"""
SendStatus - Message send operation status enumeration.

This module defines the SendStatus enum used to represent the outcome
of message send operations
"""
from enum import Enum

class SendStatus(Enum):
    """Status of a message send operation.

    Attributes:
        SENT: Message was successfully sent immediately
        QUEUED: Message failed to send and was added to retry queue
        FAILED: Message failed to send and cannot be retried
    """
    SENT = "sent"
    QUEUED = "queued"
    FAILED = "failed"
