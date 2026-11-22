"""OCR の箱 → 柱/ノンブル/ルビの除去 → 読み順 → 段落(純粋関数・標準ライブラリのみ)

入力の 1 ページ: {"w": int, "h": int, "texts": [str], "scores": [float], "boxes": [[x0,y0,x1,y1], ...]}
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from .common import MARGIN_RATIO


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class PageText:
    orientation: str
    paragraphs: list[str]
    stats: dict = field(default_factory=dict)


def to_boxes(ocr: dict, min_score: float = 0.5) -> list[Box]:
    out: list[Box] = []
    for text, score, b in zip(ocr.get("texts", []), ocr.get("scores", []), ocr.get("boxes", [])):
        if not text.strip() or score < min_score:
            continue
        out.append(Box(float(b[0]), float(b[1]), float(b[2]), float(b[3]), text, float(score)))
    return out


def page_orientation(boxes: list[Box]) -> str:
    if not boxes:
        return "empty"
    targets = [b for b in boxes if len(b.text) >= 2] or boxes
    tall = sum(1 for b in targets if b.h > 1.3 * b.w)
    return "vertical" if tall / len(targets) >= 0.5 else "horizontal"


def band_of(box: Box, page_h: float, ratio: float = MARGIN_RATIO) -> str | None:
    if box.y1 <= page_h * ratio:
        return "top"
    if box.y0 >= page_h * (1 - ratio):
        return "bottom"
    return None


_HEADER_DROP = re.compile(r"[\d\s|｜・\-‐—–:：]")


def header_key(text: str) -> str:
    return _HEADER_DROP.sub("", unicodedata.normalize("NFKC", text))


def _is_wide(box: Box, orientation: str) -> bool:
    return orientation == "horizontal" or box.w > box.h


def collect_running_heads(pages: list[tuple[list[Box], float, str]]) -> set[str]:
    """帯の中の文字列(柱)で、3 ページ以上に出るものの header_key を返す。"""
    counts: dict[str, int] = {}
    for boxes, page_h, orientation in pages:
        keys: set[str] = set()
        for b in boxes:
            if band_of(b, page_h) is None:
                continue
            k = header_key(b.text)
            if len(k) >= 4 and _is_wide(b, orientation):
                keys.add(k)
        for k in keys:
            counts[k] = counts.get(k, 0) + 1
    return {k for k, c in counts.items() if c >= 3}


_NOMBRE_ONLY = re.compile(r"^\s*\d{1,4}\s*$")


def strip_margins(
    boxes: list[Box], page_h: float, orientation: str, running_heads: set[str]
) -> tuple[list[Box], int]:
    kept: list[Box] = []
    removed = 0
    for b in boxes:
        if band_of(b, page_h) is not None:
            t = unicodedata.normalize("NFKC", b.text)
            if _NOMBRE_ONLY.match(t) or (
                header_key(b.text) in running_heads and _is_wide(b, orientation)
            ):
                removed += 1
                continue
        kept.append(b)
    return kept, removed


_RUBY = re.compile(r"[ぁ-ゖァ-ヺー]{1,8}")


def filter_ruby(boxes: list[Box], orientation: str) -> tuple[list[Box], int]:
    def thick(b: Box) -> float:
        return b.w if orientation == "vertical" else b.h

    base = [thick(b) for b in boxes if len(b.text) >= 4]
    if not base:
        return boxes, 0
    med = statistics.median(base)
    kept: list[Box] = []
    removed = 0
    for b in boxes:
        if thick(b) < 0.6 * med and _RUBY.fullmatch(b.text):
            removed += 1
            continue
        kept.append(b)
    return kept, removed


def split_tiers(boxes: list[Box], orientation: str, page_h: float) -> list[list[Box]]:
    if orientation != "vertical":
        return [boxes]
    if not boxes:
        return []
    tiers: list[list[Box]] = []
    cur_end = 0.0
    for b in sorted(boxes, key=lambda b: b.y0):
        if tiers and b.y0 - cur_end <= 0.02 * page_h:
            tiers[-1].append(b)
            cur_end = max(cur_end, b.y1)
        else:
            tiers.append([b])
            cur_end = b.y1
    return tiers


def _is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _join(parts: list[str], spaced: bool) -> str:
    """連結。spaced のとき、ASCII 英数字どうしの境目だけ空白をはさむ。"""
    out = ""
    for p in parts:
        if spaced and out and _is_ascii_alnum(out[-1]) and p and _is_ascii_alnum(p[0]):
            out += " "
        out += p
    return out


def _group(boxes: list[Box], lo, hi, center, order_key, reverse: bool) -> list[list[Box]]:
    """center で並べ、直前のグループと [lo,hi] 軸の重なりが 0.5*min(幅) 以上なら同じグループ。"""
    groups: list[list[Box]] = []
    ext: list[float] = []  # 直前のグループの [lo, hi]
    for b in sorted(boxes, key=center, reverse=reverse):
        if groups:
            overlap = min(hi(b), ext[1]) - max(lo(b), ext[0])
            min_w = min(hi(b) - lo(b), ext[1] - ext[0])
            if overlap >= 0.5 * min_w:
                groups[-1].append(b)
                ext = [min(ext[0], lo(b)), max(ext[1], hi(b))]
                continue
        groups.append([b])
        ext = [lo(b), hi(b)]
    for g in groups:
        g.sort(key=order_key)
    return groups


def order_lines(boxes: list[Box], orientation: str) -> list[Line]:
    lines: list[Line] = []
    if orientation == "vertical":
        groups = _group(
            boxes,
            lambda b: b.x0,
            lambda b: b.x1,
            lambda b: (b.x0 + b.x1) / 2,
            lambda b: b.y0,
            True,
        )
        for g in groups:
            lines.append(
                Line(
                    "".join(b.text for b in g),
                    min(b.x0 for b in g),
                    min(b.y0 for b in g),
                    max(b.x1 for b in g),
                    max(b.y1 for b in g),
                )
            )
    else:
        groups = _group(
            boxes,
            lambda b: b.y0,
            lambda b: b.y1,
            lambda b: (b.y0 + b.y1) / 2,
            lambda b: b.x0,
            False,
        )
        for g in groups:
            lines.append(
                Line(
                    _join([b.text for b in g], True),
                    min(b.x0 for b in g),
                    min(b.y0 for b in g),
                    max(b.x1 for b in g),
                    max(b.y1 for b in g),
                )
            )
    return lines


def count_unread(ocr: dict, min_len_ratio: float = 0.15) -> int:
    """文字の領域として検出されたのに、認識結果が空だった長い箱の数。
    長い = 長辺がページの長辺の min_len_ratio 以上、かつ長辺が短辺の 3 倍以上。"""
    page_long = max(float(ocr.get("w", 0)), float(ocr.get("h", 0)))
    n = 0
    for text, b in zip(ocr.get("texts", []), ocr.get("boxes", [])):
        if text.strip():
            continue
        bw, bh = abs(float(b[2]) - float(b[0])), abs(float(b[3]) - float(b[1]))
        long_side, short_side = max(bw, bh), min(bw, bh)
        if long_side >= min_len_ratio * page_long and long_side >= 3 * short_side:
            n += 1
    return n


def _split_runs(lines: list[Line], vertical: bool) -> list[list[Line]]:
    """太さが近く、行間が詰まっている行を、ひとまとまり(run)にまとめる。"""
    runs: list[list[Line]] = []
    for ln in lines:
        if runs:
            prev = runs[-1][-1]
            if vertical:
                tp, tc = prev.x1 - prev.x0, ln.x1 - ln.x0
                dist = abs((prev.x0 + prev.x1) / 2 - (ln.x0 + ln.x1) / 2)
            else:
                tp, tc = prev.y1 - prev.y0, ln.y1 - ln.y0
                dist = abs((prev.y0 + prev.y1) / 2 - (ln.y0 + ln.y1) / 2)
            hi = max(tp, tc)
            if hi > 0 and min(tp, tc) / hi >= 0.75 and dist <= 2.5 * hi:
                runs[-1].append(ln)
                continue
        runs.append([ln])
    return runs


def build_paragraphs(lines: list[Line], orientation: str) -> list[str]:
    """行(読み順)を段落にまとめる。

    見出しや吹き出しなど別の版面の行が同じページにあっても本文の基準がずれないよう、
    太さが近く行間の詰まった行のまとまりごとに字下げ(T)と行末(B)の基準を取る。
    まとまりの中は同じ版面の行だけなので、T は最小値、B は最大値でよい
    (パーセンタイルは行数の少ないまとまりで不安定になる)。
    """
    if not lines:
        return []
    vertical = orientation == "vertical"
    paras: list[list[str]] = []
    for run in _split_runs(lines, vertical):
        if vertical:
            c = statistics.median([ln.x1 - ln.x0 for ln in run])
            top = min(ln.y0 for ln in run)
            bottom = max(ln.y1 for ln in run)
        else:
            c = statistics.median([ln.y1 - ln.y0 for ln in run])
            top = min(ln.x0 for ln in run)
            bottom = max(ln.x1 for ln in run)
        prev: Line | None = None
        for ln in run:
            ln_start = ln.y0 if vertical else ln.x0
            new = prev is None
            if not new:
                prev_end = prev.y1 if vertical else prev.x1
                if ln_start - top > 0.5 * c:
                    new = True
                elif prev_end < bottom - 1.0 * c:
                    new = True
                elif ln.text[0] in "「『（(" and prev.text[-1] in "」』）)。":
                    new = True
            if new:
                paras.append([ln.text])
            else:
                paras[-1].append(ln.text)
            prev = ln
    return [_join(p, True) for p in paras]


def page_to_text(ocr: dict, running_heads: set[str], keep_lines: bool = False) -> PageText:
    page_h = float(ocr.get("h", 0))
    boxes = to_boxes(ocr)
    orientation = page_orientation(boxes)
    boxes, removed_margin = strip_margins(boxes, page_h, orientation, running_heads)
    boxes, removed_ruby = filter_ruby(boxes, orientation)
    tiers = split_tiers(boxes, orientation, page_h)
    all_lines: list[Line] = []
    paragraphs: list[str] = []
    for tier in tiers:
        lines = order_lines(tier, orientation)
        all_lines.extend(lines)
        if not keep_lines:
            paragraphs.extend(build_paragraphs(lines, orientation))
    if keep_lines:
        paragraphs = [ln.text for ln in all_lines]
    return PageText(
        orientation=orientation,
        paragraphs=paragraphs,
        stats={
            "removed_margin": removed_margin,
            "removed_ruby": removed_ruby,
            "lines": len(all_lines),
        },
    )
