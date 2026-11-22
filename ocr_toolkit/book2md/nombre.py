"""ノンブル(印字ページ番号)の抽出と、ページ欠けの判定(純粋関数・標準ライブラリのみ)

考え方:
  PDF ページ番号 - 印字ノンブル = オフセット。
  隣接ページの裏付けがある読みだけを「アンカー」とし、同じオフセットの連続を区間にする。
  区間の境目でオフセットが減っていれば欠け、増えていれば挿入(重複を含む)と判定する。
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class PageObs:
    index: int  # PDF ページ番号(1 始まり)
    numbers: list[int]  # 余白から読めたノンブル候補(順序保持・重複なし)
    blank: bool = False  # 白紙判定


@dataclass
class Segment:
    offset: int  # PDF番号 - 印字番号
    pages: list[int]  # 裏付けのある(アンカー)PDF ページ。昇順

    @property
    def start(self) -> int:
        return self.pages[0]

    @property
    def end(self) -> int:
        return self.pages[-1]


@dataclass
class CheckResult:
    status: str  # "ok" | "missing" | "uncertain"
    total_pages: int
    anchored: int
    coverage: float
    segments: list[Segment] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    suspect_blank_removed: list[dict] = field(default_factory=list)
    extra_pages: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    order_suspects: list[dict] = field(default_factory=list)
    blank_pages: list[int] = field(default_factory=list)
    front_matter: list[int] | None = None
    back_matter: list[int] | None = None
    unnumbered_in_body: list[int] = field(default_factory=list)
    printed_by_pdf: dict[int, int] = field(default_factory=dict)
    gating: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "total_pages": self.total_pages,
            "anchored": self.anchored,
            "coverage": self.coverage,
            "segments": [
                {"offset": s.offset, "start": s.start, "end": s.end, "count": len(s.pages)}
                for s in self.segments
            ],
            "missing": self.missing,
            "suspect_blank_removed": self.suspect_blank_removed,
            "extra_pages": self.extra_pages,
            "duplicates": self.duplicates,
            "order_suspects": self.order_suspects,
            "blank_pages": self.blank_pages,
            "front_matter": self.front_matter,
            "back_matter": self.back_matter,
            "unnumbered_in_body": self.unnumbered_in_body,
            "printed_by_pdf": self.printed_by_pdf,
            "gating": self.gating,
        }


_UNIT_AFTER = "章節部編回話年月日歳%巻号"


def extract_numbers(text: str, max_value: int = 9999) -> list[int]:
    """OCR 文字列からノンブル候補(1〜max_value の整数)を出現順・重複なしで返す。"""
    t = unicodedata.normalize("NFKC", text)
    # OCR が「2 75」と割る対策: 空白をはさんだ数字を結合(変化しなくなるまで)
    while True:
        t2 = re.sub(r"(\d)[ \t　]+(\d)", r"\1\2", t)
        if t2 == t:
            break
        t = t2
    out: list[int] = []
    for m in re.finditer(r"(?<!\d)(\d{1,4})(?!\d)", t):
        pre = t[m.start() - 1] if m.start() > 0 else ""
        post = t[m.end()] if m.end() < len(t) else ""
        if pre == "第":
            continue
        if post and post in _UNIT_AFTER:
            continue
        if pre == "." or post == ".":
            continue
        v = int(m.group(1))
        if 1 <= v <= max_value and v not in out:
            out.append(v)
    return out


def _runs(chosen: dict[int, int]) -> list[Segment]:
    """chosen(ページ→オフセット)を PDF 順に並べ、同じオフセットの連続を区間にする。"""
    segs: list[Segment] = []
    for i in sorted(chosen):
        k = chosen[i]
        if segs and segs[-1].offset == k:
            segs[-1].pages.append(i)
        else:
            segs.append(Segment(offset=k, pages=[i]))
    return segs


def analyze(
    pages: list[PageObs],
    *,
    window: int = 3,
    min_seg: int = 3,
    min_anchored: int = 10,
    min_coverage: float = 0.3,
    strict: bool = False,
) -> CheckResult:
    n = len(pages)
    for pos, p in enumerate(pages, start=1):
        if p.index != pos:
            raise ValueError("pages は index 1..N が昇順で全部そろっている必要があります")
    cand: dict[int, list[int]] = {
        p.index: [v for v in p.numbers if 1 <= v <= n + 200] for p in pages
    }

    # 手順 1: アンカー(隣の裏付けのある読み)
    def support(i: int, v: int) -> int:
        k = i - v
        return sum(
            1
            for j in range(max(1, i - window), min(n, i + window) + 1)
            if j != i and (j - k) in cand[j]
        )

    chosen: dict[int, int] = {}
    prev_offset: int | None = None
    for i in range(1, n + 1):
        scored = [(support(i, v), v) for v in cand[i]]
        scored = [(s, v) for s, v in scored if s >= 1]
        if not scored:
            continue
        best = max(s for s, _ in scored)
        tops = [v for s, v in scored if s == best]
        pick = tops[0]
        if prev_offset is not None:
            for v in tops:
                if i - v == prev_offset:
                    pick = v
                    break
        chosen[i] = i - pick
        prev_offset = i - pick

    # 手順 2: 区間化とノイズ除去
    while True:
        segs = _runs(chosen)
        small = [s for s in segs if len(s.pages) < min_seg]
        if not small:
            break
        for s in small:
            for pg in s.pages:
                del chosen[pg]
    segments = segs

    # 手順 3: 判定不能
    anchored = sum(len(s.pages) for s in segments)
    uncertain = (not segments) or anchored < max(min_anchored, math.ceil(min_coverage * n))

    # 手順 4: 区間の境目
    missing: list[dict] = []
    suspects: list[dict] = []
    extra: list[dict] = []
    dups: list[dict] = []
    for a, b in zip(segments, segments[1:]):
        ka, ea = a.offset, a.end
        kb, sb = b.offset, b.start
        pa, pb = ea - ka, sb - kb
        d = ka - kb
        between = range(ea + 1, sb)
        if d > 0:
            rng = set(range(pa + 1, pb))
            present = {c for j in between for c in cand[j] if c in rng}
            exact = sorted(rng - present) if len(rng) - len(present) == d else None
            gap = {
                "after_pdf": ea,
                "before_pdf": sb,
                "printed_from": pa + 1,
                "printed_to": pb - 1,
                "count": d,
                "exact": exact,
            }
            if d == 1 and len(between) >= 1 and not cand[ea + 1]:
                suspects.append(gap)
            else:
                missing.append(gap)
        elif d < 0:
            if pb <= pa:
                for v in range(max(pb, a.start - ka), min(pa, b.end - kb) + 1):
                    dups.append({"printed": v, "pdf_pages": [v + ka, v + kb]})
            else:
                extra.append({"after_pdf": ea, "before_pdf": sb, "count": -d})

    # 手順 5: 入れ替わりの疑い
    anchor_set = {pg for s in segments for pg in s.pages}
    order_suspects: list[dict] = []
    for s in segments:
        k = s.offset
        for j in range(s.start, s.end + 1):
            if j in anchor_set:
                continue
            e = j - k
            if e in cand[j]:
                continue
            for dd in (-2, -1, 1, 2):
                if (j + dd - k) in cand[j]:
                    order_suspects.append({"pdf_page": j, "read": j + dd - k, "expected": e})
                    break

    # 手順 6: その他
    printed_by_pdf: dict[int, int] = {}
    for s in segments:
        for j in range(s.start, s.end + 1):
            printed_by_pdf[j] = j - s.offset
    front = back = None
    unnumbered: list[int] = []
    if segments:
        first, last = segments[0], segments[-1]
        if first.start > 1:
            front = [1, first.start - 1]
        if last.end < n:
            back = [last.end + 1, n]
        unnumbered = [j for j in range(first.start, last.end + 1) if j not in anchor_set]

    gating: list[str] = []
    if uncertain:
        status = "uncertain"
        gating = ["uncertain"]
    elif missing:
        status = "missing"
        gating = ["missing"]
    elif strict and suspects:
        status = "missing"
        gating = ["suspect_blank_removed"]
    else:
        status = "ok"

    return CheckResult(
        status=status,
        total_pages=n,
        anchored=anchored,
        coverage=round(anchored / n, 3) if n else 0.0,
        segments=segments,
        missing=missing,
        suspect_blank_removed=suspects,
        extra_pages=extra,
        duplicates=dups,
        order_suspects=order_suspects,
        blank_pages=[p.index for p in pages if p.blank],
        front_matter=front,
        back_matter=back,
        unnumbered_in_body=unnumbered,
        printed_by_pdf=printed_by_pdf,
        gating=gating,
    )
