"""Test OCRHandler text extraction from images using EasyOCR."""
import sys
import os
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
from datetime import datetime, timezone
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from OCRHandler import OCRHandler


def test_is_available_false_when_no_easyocr():
    """Test availability check when EasyOCR not installed."""
    with patch('OCRHandler._EASYOCR_AVAILABLE', False):
        handler = OCRHandler()
        assert not handler.is_available()


def test_extract_text_when_unavailable():
    """Test extraction returns None when OCR unavailable."""
    with patch('OCRHandler._EASYOCR_AVAILABLE', False):
        handler = OCRHandler()
        text = handler.extract_text("/tmp/test.png")
        assert text is None


def test_ocr_enabled_for_some_destinations_not_others():
    """
    Test that OCR is processed for destinations that need it, but not for others.

    Scenario: Same Telegram channel routes to 2 destinations:
    - Destination A: OCR enabled
    - Destination B: OCR disabled

    Expected: OCR should be extracted once and used only for Destination A.
    """
    from Watchtower import Watchtower
    from MessageData import MessageData

    # Create mock config with two destinations, one with OCR
    mock_config = Mock()
    mock_config.tmp_dir = Path("/tmp")
    mock_config.attachments_dir = Mock()
    mock_config.attachments_dir.exists.return_value = True
    mock_config.attachments_dir.glob.return_value = []

    mock_config.destinations = [
        {
            'name': 'Dest A (OCR enabled)',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook_a',
            'channels': [{
                'id': '@test_channel',
                'keywords': [],
                'restricted_mode': False,
                'parser': None,
                'ocr': True
            }]
        },
        {
            'name': 'Dest B (OCR disabled)',
            'type': 'Discord',
            'discord_webhook_url': 'https://discord.com/webhook_b',
            'channels': [{
                'id': '@test_channel',
                'keywords': [],
                'restricted_mode': False,
                'parser': None,
                'ocr': False
            }]
        }
    ]

    mock_telegram = Mock()
    mock_telegram.client = Mock()
    mock_telegram.client.is_connected = Mock(return_value=False)

    mock_router = Mock()
    mock_router.get_destinations = Mock(return_value=[
        {'name': 'Dest A', 'type': 'Discord', 'discord_webhook_url': 'url_a', 'parser': None,
         'restricted_mode': False, 'ocr': True, 'keywords': []},
        {'name': 'Dest B', 'type': 'Discord', 'discord_webhook_url': 'url_b', 'parser': None,
         'restricted_mode': False, 'ocr': False, 'keywords': []}
    ])
    mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)
    mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

    mock_ocr = Mock()
    mock_ocr.is_available = Mock(return_value=True)
    mock_ocr.extract_text = Mock(return_value="OCR extracted text")

    mock_discord = Mock()
    mock_discord.send_message = AsyncMock(return_value=True)
    mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text or "")

    mock_queue = Mock()
    mock_queue.get_queue_size = Mock(return_value=0)

    mock_metrics = Mock()

    app = Watchtower(
        sources=['telegram'],
        config=mock_config,
        telegram=mock_telegram,
        discord=mock_discord,
        router=mock_router,
        ocr=mock_ocr,
        message_queue=mock_queue,
        metrics=mock_metrics
    )

    test_image_path = str(Path(__file__).parent / "test-img.jpg")

    msg = MessageData(
        source_type="Telegram",
        channel_id="@test_channel",
        channel_name="Test Channel",
        username="@user",
        timestamp=datetime.now(timezone.utc),
        text="Regular text",
        has_attachments=True,
        attachment_type="photo",
        attachment_path=test_image_path
    )
    msg.original_message = Mock()

    with patch('os.path.exists', return_value=True), \
         patch('os.remove') as mock_remove:
        asyncio.run(app._handle_message(msg, False))

    mock_ocr.extract_text.assert_called_once()
    assert mock_discord.send_message.call_count == 2, "Message should be sent to both destinations"
