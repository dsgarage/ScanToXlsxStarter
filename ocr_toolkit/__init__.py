"""lambda-ocr: PDF/画像スキャン → 高精度OCR → 構造化データ パイプライン"""
__version__ = "0.1.0"

from .fix_ocr import fix_ocr, OCR_FIXES
from .paddle_ocr import BatchOCR
from .pdf_tools import pdf_to_png, crop_regions

__all__ = [
    "fix_ocr",
    "OCR_FIXES",
    "BatchOCR",
    "pdf_to_png",
    "crop_regions",
]
