"""
OCRHandler - Optical Character Recognition for image text extraction

This module provides OCR capabilities using EasyOCR to extract text from images.
Primary use case is extracting text from screenshots for keyword matching and routing.

Features:
- Lazy initialization of OCR reader (only loads when needed)
- Graceful degradation when EasyOCR is not installed
- Optimized parameters for screenshot text extraction
- English language support

Dependencies:
    - easyocr (optional): pip install easyocr
    If not installed, OCR features will be disabled but app continues to function.
"""
from typing import Optional
from LoggerSetup import setup_logger

# Optional EasyOCR import (if missing, log and skip OCR)
try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except Exception:
    _EASYOCR_AVAILABLE = False

_logger = setup_logger(__name__)


class OCRHandler:
    """Handles OCR operations for image text extraction.

    Uses EasyOCR library for text recognition. Reader is lazily initialized
    on first use to avoid startup delays when OCR is not needed.
    """

    def __init__(self):
        """Initialize OCRHandler with lazy reader loading."""
        self._ocr_reader = None

    def is_available(self) -> bool:
        """Check if OCR is available.

        Returns:
            bool: True if EasyOCR is installed and available, False otherwise
        """
        return _EASYOCR_AVAILABLE

    def _ensure_reader(self) -> None:
        """Lazily initialize the OCR reader on first use.

        Creates EasyOCR Reader instance configured for English text extraction
        with CPU processing. If initialization fails, reader remains None and
        subsequent extract_text() calls will return None.
        """
        if self._ocr_reader is None and _EASYOCR_AVAILABLE:
            try:
                # English only, CPU mode for simplicity
                self._ocr_reader = easyocr.Reader(['en'], gpu=False)
                _logger.info("[OCRHandler] EasyOCR reader initialized (en, CPU)")
            except Exception as e:
                _logger.error(f"[OCRHandler] Failed to initialize EasyOCR: {e}")
                self._ocr_reader = None

    def extract_text(self, image_path: str) -> Optional[str]:
        """Run OCR on a single image and return extracted text.

        Args:
            image_path: Path to image file to process

        Returns:
            Optional[str]: Extracted text if successful, None if OCR unavailable or failed

        Note:
            EasyOCR parameters are tuned for screenshot text extraction:
            - contrast_ths=0.15: Lower threshold to detect faint text
            - min_size=10: Ignore tiny noise artifacts
            - paragraph=True: Group text into logical blocks
        """
        if not _EASYOCR_AVAILABLE:
            _logger.debug("[OCRHandler] OCR skipped (EasyOCR not available)")
            return None

        self._ensure_reader()
        if self._ocr_reader is None:
            return None

        try:
            # EasyOCR parameters tuned for screenshot text extraction:
            # - contrast_ths=0.15: Lower threshold to detect faint text
            # - min_size=10: Ignore tiny noise artifacts
            # - detail=0: Return only text (not coordinates)
            # - paragraph=True: Group text into logical blocks
            results = self._ocr_reader.readtext(
                image_path,
                detail=0,
                paragraph=True,
                contrast_ths=0.15,
                min_size=10
            )
            text = "\n".join([s for s in results if s])
            return text.strip() or None
        except Exception as e:
            _logger.error(f"[OCRHandler] OCR failed on {image_path}: {e}")
            return None
