"""1 冊分の Markdown 文字列を組み立てる(標準ライブラリと fix_ocr のみ)"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..fix_ocr import fix_ocr


@dataclass
class PageEntry:
    index: int
    printed: int | None
    blank: bool
    paragraphs: list[str]


def build_markdown(
    *,
    title: str,
    source_name: str,
    pages: list[PageEntry],
    page_check: str,
    missing_suspects: list[dict],
    ocr_info: dict,
    generated: str,
    apply_fix: bool = False,
) -> str:
    head = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"source: {json.dumps(source_name, ensure_ascii=False)}",
        f"pdf_pages: {len(pages)}",
        f"page_check: {page_check}",
    ]
    if missing_suspects:
        items = [
            {"printed_from": s.get("printed_from"), "printed_to": s.get("printed_to")}
            for s in missing_suspects
        ]
        head.append(f"suspect_blank_removed: {json.dumps(items, ensure_ascii=False)}")
    head += [
        f"ocr_model: {ocr_info.get('model')}",
        f"ocr_device: {ocr_info.get('device')}",
        f"generated: {generated}",
        "tool: ocr_toolkit book2md",
        "---",
    ]

    blocks: list[str] = ["\n".join(head)]
    for pg in pages:
        printed = "-" if pg.printed is None else str(pg.printed)
        marker = f"<!-- page: {pg.index} printed: {printed}{' blank' if pg.blank else ''} -->"
        blocks.append(marker)
        for para in pg.paragraphs:
            text = fix_ocr(para) if apply_fix else para
            text = text.replace("-->", "-- >").strip()
            if text:
                blocks.append(text)
    return "\n\n".join(blocks) + "\n"
