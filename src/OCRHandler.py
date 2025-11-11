"""
OCRHandler - Optical Character Recognition for text extraction from images

This module uses EasyOCR to extract text from images for keyword matching and routing.
If the EasyOCR import fails, it is logged and OCR functionality is disabled without crashing.
"""
from typing import Optional
from LoggerSetup import setup_logger

try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except Exception:
    _EASYOCR_AVAILABLE = False

_logger = setup_logger(__name__)


class OCRHandler:
    """Handles OCR operations using EasyOCR.
    """

    def __init__(self):
        """Initialize OCRHandler with lazy reader loading to avoid startup delays
        when OCR is not needed."""
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
                # English only, CPU mode
                self._ocr_reader = easyocr.Reader(['en'], gpu=False)
                _logger.info("EasyOCR reader initialized (en, CPU)")
            except Exception as e:
                _logger.error(f"Failed to initialize EasyOCR: {e}")
                self._ocr_reader = None

    def extract_text(self, image_path: str) -> Optional[str]:
        """Run OCR on a single image and return extracted text.

        Args:
            image_path: Path to image file to process

        Returns:
            Optional[str]: Extracted text if successful, None if OCR unavailable or failed
        """
        if not _EASYOCR_AVAILABLE:
            _logger.debug("OCR skipped (EasyOCR not available)")
            return None

        self._ensure_reader()
        if self._ocr_reader is None:
            return None

        try:
            # EasyOCR parameters tuning:
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
            _logger.error(f"OCR failed on {image_path}: {e}")
            return None
