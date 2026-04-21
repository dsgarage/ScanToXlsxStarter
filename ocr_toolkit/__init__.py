"""ScanToXlsxStarter: PDF/画像スキャン → 高精度OCR → 構造化データ パイプライン"""
__version__ = "0.4.0"

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
from .progress import (
    TOC,
    Section,
    State,
    SectionState,
    StageState,
    load_toc,
    load_state,
    save_state,
    mark,
    is_done,
    pending_sections,
    render_status_table,
    summary_counts,
    ALL_STAGES,
    STAGE_COSTS,
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
    # TOC ベースの進捗管理
    "TOC",
    "Section",
    "State",
    "SectionState",
    "StageState",
    "load_toc",
    "load_state",
    "save_state",
    "mark",
    "is_done",
    "pending_sections",
    "render_status_table",
    "summary_counts",
    "ALL_STAGES",
    "STAGE_COSTS",
]

# preview はオプション (openpyxl 依存)。明示 import で利用可能。
