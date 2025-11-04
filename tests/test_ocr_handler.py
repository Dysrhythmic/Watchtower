import unittest
import sys
import os
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from OCRHandler import OCRHandler


class TestOCRHandler(unittest.TestCase):
    """Test OCRHandler."""

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


if __name__ == '__main__':
    unittest.main()
