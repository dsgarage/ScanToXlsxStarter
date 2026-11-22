"""PDF → ページ JPEG、白紙判定、余白の連結画像(Pillow, pypdfium2)"""
from __future__ import annotations

import io
from pathlib import Path

from .common import MARGIN_RATIO

RENDER_DPI = 200


def _try_raw_jpeg(page, pdfium) -> bytes | None:
    """1 ページ 1 画像・DCTDecode・回転なし・全面配置なら JPEG のバイト列をそのまま返す。"""
    from PIL import Image

    if page.get_rotation() != 0:
        return None
    objs = [o for o in page.get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
    if len(objs) != 1:
        return None
    o = objs[0]
    if o.get_filters() != ["DCTDecode"]:
        return None
    a, b, c, d, _e, _f = o.get_matrix().get()
    if not (b == 0 and c == 0 and a > 0 and d > 0):
        return None
    buf = io.BytesIO()
    o.extract(buf)
    data = buf.getvalue()
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "JPEG" or im.mode not in ("RGB", "L"):
                return None
    except Exception:
        return None
    return data


def extract_pages(pdf_path, out_dir) -> list[dict]:
    """各ページを out_dir/pNNNN.jpg に書く。既にあって 0 バイトでなければ作らない(再開)。"""
    import pypdfium2 as pdfium
    from PIL import Image

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Windows で非 ASCII パスを避けるため常にバイト列で開く
    doc = pdfium.PdfDocument(Path(pdf_path).read_bytes())
    results: list[dict] = []
    try:
        for i in range(1, len(doc) + 1):
            name = f"p{i:04d}.jpg"
            dest = out / name
            page = doc[i - 1]
            try:
                method = "raw"
                if dest.exists() and dest.stat().st_size > 0:
                    with Image.open(dest) as im:
                        w, h = im.size
                    # 再開時の方法は記録が無いので、生の取り出し可否だけ再判定する
                    method = "raw" if _try_raw_jpeg(page, pdfium) is not None else "render"
                else:
                    data = _try_raw_jpeg(page, pdfium)
                    if data is not None:
                        tmp = dest.with_name(dest.name + ".tmp")
                        tmp.write_bytes(data)
                        tmp.replace(dest)
                        with Image.open(dest) as im:
                            w, h = im.size
                    else:
                        method = "render"
                        img = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
                        tmp = dest.with_name(dest.name + ".tmp")
                        img.save(tmp, format="JPEG", quality=95)
                        tmp.replace(dest)
                        w, h = img.size
            finally:
                page.close()
            results.append({"index": i, "file": name, "method": method, "w": w, "h": h})
    finally:
        doc.close()
    return results


def ink_ratio(gray) -> float:
    """幅 200px に縮小し、四辺 5% を切り落として、画素値 < 128 の割合を返す。"""
    from PIL import Image

    g = gray.convert("L")
    w, h = g.size
    if w <= 0 or h <= 0:
        return 0.0
    nw = 200
    nh = max(1, round(h * nw / w))
    g = g.resize((nw, nh), Image.BILINEAR)
    mx, my = int(nw * 0.05), int(nh * 0.05)
    g = g.crop((mx, my, nw - mx, nh - my))
    px = g.tobytes()
    if not px:
        return 0.0
    dark = sum(1 for v in px if v < 128)
    return dark / len(px)


def page_stats(img_path) -> dict:
    from PIL import Image

    with Image.open(img_path) as im:
        ink = ink_ratio(im)
    return {"blank": ink < 0.002, "ink": round(ink, 5)}


def make_margin_composite(img_path, out_path, ratio: float = MARGIN_RATIO, gap: int = 20) -> dict:
    """画像の上下 ratio の帯を、白い隙間 gap px をはさんで縦に連結して PNG で保存。既にあれば作らない。"""
    from PIL import Image

    with Image.open(img_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        m = int(h * ratio)
        outp = Path(out_path)
        if not (outp.exists() and outp.stat().st_size > 0):
            outp.parent.mkdir(parents=True, exist_ok=True)
            top = im.crop((0, 0, w, m))
            bottom = im.crop((0, h - m, w, h))
            canvas = Image.new("RGB", (w, m * 2 + gap), (255, 255, 255))
            canvas.paste(top, (0, 0))
            canvas.paste(bottom, (0, m + gap))
            tmp = outp.with_name(outp.name + ".tmp")
            canvas.save(tmp, format="PNG")
            tmp.replace(outp)
    return {"top_h": m, "gap": gap}
