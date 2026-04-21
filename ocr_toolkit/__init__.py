"""ScanToXlsxStarter: PDF/画像スキャン → 高精度OCR → 構造化データ パイプライン"""
__version__ = "0.3.0"

from .fix_ocr import fix_ocr, OCR_FIXES
from .paddle_ocr import BatchOCR
from .pdf_tools import pdf_to_png, crop_regions
from .corrections import (
    apply_corrections,
    diff_summary,
    load_merged,
    load_module,
    validate,
    CorrectionError,
)
from .suspicion import (
    score_text,
    score_row,
    partition_by_threshold,
    DEFAULT_WEIGHTS,
)

__all__ = [
    "fix_ocr",
    "OCR_FIXES",
    "BatchOCR",
    "pdf_to_png",
    "crop_regions",
    # LLM 校正パイプライン
    "apply_corrections",
    "diff_summary",
    "load_merged",
    "load_module",
    "validate",
    "CorrectionError",
    # 崩壊スコア (LLM pre-filter)
    "score_text",
    "score_row",
    "partition_by_threshold",
    "DEFAULT_WEIGHTS",
]

# preview はオプション (openpyxl 依存)。明示 import で利用可能。
