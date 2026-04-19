"""PDF→PNG化、画像クロップユーティリティ"""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Iterable


def pdf_to_png(
    pdf_path: str | Path,
    out_dir: str | Path,
    *,
    first_page: int = 1,
    last_page: int | None = None,
    dpi: int = 300,
    prefix: str = "page",
) -> Path:
    """PDFをページ番号付きPNGに変換。

    Args:
        pdf_path: 入力PDFのパス
        out_dir: 出力先ディレクトリ(なければ作成)
        first_page / last_page: ページ範囲(1始まり)
        dpi: 解像度。300が書籍スキャンに対する推奨値
        prefix: 出力ファイル名の接頭辞(`page-001.png` など)

    Returns:
        出力ディレクトリのPath
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["pdftoppm", "-r", str(dpi)]
    cmd += ["-f", str(first_page)]
    if last_page is not None:
        cmd += ["-l", str(last_page)]
    cmd += [str(pdf_path), str(out / prefix), "-png"]
    subprocess.run(cmd, check=True)
    return out


def crop_regions(
    src_png: str | Path,
    regions: dict[str, tuple[int, int, int, int]],
    out_dir: str | Path,
    *,
    stem: str,
) -> dict[str, Path]:
    """1枚のPNGから複数の矩形領域を切り出し、それぞれ別名で保存。

    Args:
        src_png: 元画像
        regions: {領域名: (left, top, right, bottom)} のdict
        out_dir: 出力先
        stem: ファイル名の幹(`{stem}-{region_name}.png` として保存)

    Returns:
        {領域名: 出力Path} のdict
    """
    from PIL import Image

    src = Image.open(src_png)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, box in regions.items():
        path = out / f"{stem}-{name}.png"
        src.crop(box).save(path)
        result[name] = path
    return result
