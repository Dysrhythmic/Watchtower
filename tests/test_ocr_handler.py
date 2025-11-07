"""
Test OCRHandler - Text extraction from images using EasyOCR

This module tests the OCRHandler component which extracts text from images
(screenshots, photos) for keyword matching and routing.

What This Tests:
    - Availability check when EasyOCR installed/not installed
    - Text extraction from images
    - Handling empty OCR results
    - Error handling during OCR processing
    - Reader initialization (should only initialize once)
    - Integration with actual image files

Test Pattern - Basic OCR:
    1. Mock easyocr.Reader class with @patch decorator
    2. Configure mock reader's readtext() return value
    3. Patch _EASYOCR_AVAILABLE to True
    4. Create OCRHandler instance
    5. Call extract_text() with image path
    6. Assert text matches expected output

Test Pattern - Availability:
    1. Patch _EASYOCR_AVAILABLE to False
    2. Create OCRHandler instance
    3. Call is_available()
    4. Assert returns False

Mock Setup Template:
    @patch('easyocr.Reader')
    def test_extraction(self, mock_reader_class):
        # Configure mock
        mock_reader = Mock()
        mock_reader.readtext.return_value = ["Line 1", "Line 2"]
        mock_reader_class.return_value = mock_reader

        # Patch availability
        with patch('OCRHandler._EASYOCR_AVAILABLE', True):
            handler = OCRHandler()
            handler._ensure_reader()
            text = handler.extract_text("/path/to/image.png")
            # Assert text content

How to Add New Tests:
    1. Add test method starting with test_
    2. Use descriptive docstring describing what OCR behavior is tested""
    3. Mock easyocr.Reader if testing extraction
    4. Patch _EASYOCR_AVAILABLE to control availability
    5. Use self.assertIn/assertIsNone for text verification
    6. For error tests: use side_effect=Exception("error")
    7. For integration tests: use actual test images from tests/ directory
"""
import unittest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from OCRHandler import OCRHandler


class TestOCRHandler(unittest.TestCase):
    """Test OCRHandler text extraction from images."""

    def test_is_available_false_when_no_easyocr(self):
        """Test availability check when EasyOCR not installed."""
        with patch('OCRHandler._EASYOCR_AVAILABLE', False):
            handler = OCRHandler()
            self.assertFalse(handler.is_available())

    @patch('easyocr.Reader')
    def test_extract_text_success(self, mock_reader_class):
        """Test text extraction from image."""
        mock_reader = Mock()
        mock_reader.readtext.return_value = ["Line 1", "Line 2"]
        mock_reader_class.return_value = mock_reader

        with patch('OCRHandler._EASYOCR_AVAILABLE', True):
            handler = OCRHandler()
            handler._ensure_reader()
            text = handler.extract_text("/tmp/test.png")
            self.assertIn("Line 1", text)
            self.assertIn("Line 2", text)

    @patch('easyocr.Reader')
    def test_extract_text_empty_result(self, mock_reader_class):
        """Test handling empty OCR result."""
        mock_reader = Mock()
        mock_reader.readtext.return_value = []
        mock_reader_class.return_value = mock_reader

        with patch('OCRHandler._EASYOCR_AVAILABLE', True):
            handler = OCRHandler()
            handler._ensure_reader()
            text = handler.extract_text("/tmp/test.png")
            self.assertIsNone(text)

    def test_extract_text_when_unavailable(self):
        """Test extraction returns None when OCR unavailable."""
        with patch('OCRHandler._EASYOCR_AVAILABLE', False):
            handler = OCRHandler()
            text = handler.extract_text("/tmp/test.png")
            self.assertIsNone(text)

    @patch('easyocr.Reader')
    def test_extract_text_handles_error(self, mock_reader_class):
        """Test handling OCR processing errors."""
        mock_reader = Mock()
        mock_reader.readtext.side_effect = Exception("OCR failed")
        mock_reader_class.return_value = mock_reader

        with patch('OCRHandler._EASYOCR_AVAILABLE', True):
            handler = OCRHandler()
            handler._ensure_reader()
            text = handler.extract_text("/tmp/test.png")
            self.assertIsNone(text)

    @patch('easyocr.Reader')
    def test_reader_initialization_once(self, mock_reader_class):
        """Test reader is only initialized once."""
        mock_reader = Mock()
        mock_reader.readtext.return_value = ["text"]
        mock_reader_class.return_value = mock_reader

        with patch('OCRHandler._EASYOCR_AVAILABLE', True):
            handler = OCRHandler()
            handler._ensure_reader()
            handler._ensure_reader()  # Call twice

            # Reader should only be created once
            mock_reader_class.assert_called_once()


class TestOCRMultipleDestinations(unittest.TestCase):
    """
    Integration test for OCR with multiple destinations.

    Tests that when a single message routes to multiple destinations,
    OCR is processed correctly for destinations that need it, but not for others.
    """

    def test_ocr_enabled_for_some_destinations_not_others(self):
        """
        Test that OCR is processed for destinations that need it, but not for others.

        Scenario: Same Telegram channel routes to 2 destinations:
        - Destination A: OCR enabled
        - Destination B: OCR disabled

        Expected: OCR should be extracted once and used only for Destination A.
        """
        from Watchtower import Watchtower
        from MessageData import MessageData
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest.mock import Mock, patch, AsyncMock
        import asyncio
        import os

        # Create mock config with two destinations, one with OCR
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        mock_config.destinations = [
            {
                'name': 'Dest A (OCR enabled)',
                'type': 'discord',
                'discord_webhook_url': 'https://discord.com/webhook_a',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': True  # OCR enabled
                }]
            },
            {
                'name': 'Dest B (OCR disabled)',
                'type': 'discord',
                'discord_webhook_url': 'https://discord.com/webhook_b',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False  # OCR disabled
                }]
            }
        ]

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)

        mock_router = Mock()
        mock_router.get_destinations = Mock(return_value=[
            {'name': 'Dest A', 'type': 'discord', 'webhook_url': 'url_a', 'parser': None,
             'restricted_mode': False, 'ocr': True, 'keywords': []},
            {'name': 'Dest B', 'type': 'discord', 'webhook_url': 'url_b', 'parser': None,
             'restricted_mode': False, 'ocr': False, 'keywords': []}
        ])
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)  # At least one dest has OCR
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock(return_value="OCR extracted text")

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text or "")

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
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

        # Get path to actual test image
        test_image_path = str(Path(__file__).parent / "test-img.jpg")

        # Create message with media using actual test image
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Regular text",
            has_media=True,
            media_type="photo",
            media_path=test_image_path
        )
        msg.original_message = Mock()

        # Mock os.path.exists to return True for exists checks but prevent file deletion
        # Also mock os.remove to prevent deletion of the test fixture
        with patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_remove:
            # Process message
            asyncio.run(app._handle_message(msg, False))

        # Verify OCR was called exactly once
        mock_ocr.extract_text.assert_called_once()

        # Verify message was sent to both destinations
        self.assertEqual(mock_discord.send_message.call_count, 2,
            "Message should be sent to both destinations")


if __name__ == '__main__':
    unittest.main()
