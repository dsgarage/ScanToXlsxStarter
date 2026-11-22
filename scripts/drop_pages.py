"""検証用: PDF から指定ページを抜いた PDF を作る(pypdfium2。描画しないので軽い)

使い方:
    python scripts/drop_pages.py <in.pdf> <out.pdf> --drop 150,201,202

--drop は PDF ページ番号(1 始まり)。PDF はリポジトリに入れない(.gitignore に *.pdf 済み)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_drop(spec: str) -> set[int]:
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if part:
            pages.add(int(part))
    return pages


def drop_pages(src: Path, dest: Path, drop: set[int]) -> tuple[int, int]:
    """(元のページ数, 出力のページ数) を返す。"""
    import pypdfium2 as pdfium

    # Windows で非 ASCII パスを避けるため、バイト列で開く
    doc = pdfium.PdfDocument(Path(src).read_bytes())
    try:
        total = len(doc)
        bad = sorted(p for p in drop if p < 1 or p > total)
        if bad:
            raise ValueError(f"範囲外のページ番号: {bad} (全 {total} ページ)")
        keep = [i for i in range(total) if (i + 1) not in drop]
        if not keep:
            raise ValueError("全ページを抜くことはできません")
        new = pdfium.PdfDocument.new()
        try:
            new.import_pages(doc, keep)
            new.save(str(dest))
        finally:
            new.close()
        return total, len(keep)
    finally:
        doc.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PDF から指定ページを抜く(検証用)")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--drop", required=True, help="抜くページ(1 始まり、カンマ区切り)")
    a = ap.parse_args(argv)
    try:
        total, kept = drop_pages(Path(a.input), Path(a.output), parse_drop(a.drop))
    except (ValueError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"{total} ページ → {kept} ページ: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
