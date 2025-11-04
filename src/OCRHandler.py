import logging
from typing import Optional

# Optional EasyOCR import (if missing, log and skip OCR)
try:
    import easyocr
    _EASYOCR_AVAILABLE = True
except Exception:
    _EASYOCR_AVAILABLE = False

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class OCRHandler:
    """Handles OCR operations for image text extraction."""

    def __init__(self):
        self._ocr_reader = None

    def is_available(self) -> bool:
        """Check if OCR is available."""
        return _EASYOCR_AVAILABLE

    def _ensure_reader(self):
        """Lazily initialize the OCR reader."""
        if self._ocr_reader is None and _EASYOCR_AVAILABLE:
            try:
                # English only, CPU mode for simplicity
                self._ocr_reader = easyocr.Reader(['en'], gpu=False)
                logger.info("[OCRHandler] EasyOCR reader initialized (en, CPU)")
            except Exception as e:
                logger.error(f"[OCRHandler] Failed to initialize EasyOCR: {e}")
                self._ocr_reader = None

    def extract_text(self, image_path: str) -> Optional[str]:
        """Run OCR on a single image and return raw text."""
        if not _EASYOCR_AVAILABLE:
            logger.debug("[OCRHandler] OCR skipped (EasyOCR not available)")
            return None

        self._ensure_reader()
        if self._ocr_reader is None:
            return None

        try:
            results = self._ocr_reader.readtext(image_path, detail=0, paragraph=True, contrast_ths=0.15, min_size=10)
            text = "\n".join([s for s in results if s])
            return text.strip() or None
        except Exception as e:
            logger.error(f"[OCRHandler] OCR failed on {image_path}: {e}")
            return None
