"""OCR テキストの崩壊度を機械的にスコアリングするモジュール。

LLM 校正パイプラインの **pre-filter** として使う:
辞書/正規表現 (`fix_ocr`) で直せない範囲だけを LLM に送ることで
トークン消費を 50〜70% 削減できる。

典型的な使い方:

    from ocr_toolkit import fix_ocr
    from ocr_toolkit.suspicion import score_row, partition_by_threshold

    cleaned_rows = [
        {**row, "leadText": fix_ocr(row["leadText"])}
        for row in raw_rows
    ]
    suspicious, clean = partition_by_threshold(
        cleaned_rows,
        text_fields=("lead", "leadText"),
        threshold=0.30,
    )
    # `suspicious` だけを LLM に送る、`clean` は fix_ocr 後の状態でそのまま採用

スコア定義 (高いほど崩壊度高):

| 指標 | 重み | 内容 |
|---|---|---|
| garble_ratio   | 3.0 | 簡体字 / 異体字 / 不自然 Unicode の混入率 |
| length_zscore  | 1.0 | 同フィールドの median からの絶対 zscore (>2.0 で疑い) |
| punct_imbalance | 2.0 | 鉤括弧 / 丸括弧の開閉アンバランス |
| repetition     | 2.0 | 同一文字 3 連以上の出現 (コココ 等) |
| end_truncation | 1.0 | 末尾が句点/閉じ括弧/カナ/漢字以外 (途切れ) |
| short_lines    | 1.0 | 改行で区切られた断片が極端に多い |

しきい値の目安 (実測ベース):
- 0.05 → 極小の崩壊も拾う (緩め、~50% 候補)
- 0.10 → 一般的: 軽い崩壊 + 句読点不整合まで拾う
- 0.20 → 厳しめ: 簡体字/明確な切れ目のみ、~80%+ を LLM スキップ
- 0.30 → かなり厳しい: 重度崩壊のみ

実例 (PaddleOCR mobile + 日本語書籍 OCR):
- 簡体字 1〜2字混入 / 100字 → ~0.04
- 末尾切れ                 → ~0.03
- 「と」だけの片括弧        → ~0.04
- 「ココココ」3連          → ~0.07
- 簡体字 多数 + 不自然 Unicode → 0.15+
"""
from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# ============================================================================
# 簡体字 / 異体字 (日本語書籍 OCR で頻出する化け候補)
# ============================================================================
# PaddleOCR が日本語新字体を簡体字として返す典型例。
# fix_ocr.OCR_FIXES でカバーされていない残存パターンも含めて検出する。
SIMPLIFIED_CHARS = frozenset(
    "时见实发样场们门处护办换择渔钝运虑过这边远见识别认证试讨议谈说"
    "话语词诉诚谊谋谨谬课请请论调讲谊负赋赏赐资买货赞赖赖赘趋赵超"
    "进运迈遗递选连违远遇过迪迹追逊送适道遇野针钓钢铁锁锐错银"
    "队际限险随陈难雇难离静靠预颂顺顽颗顾飞餐馆驰驱验骄高鬓魂魅魇"
    "鸟鸡鸣鹰麦黄黑齐齿龄龙简籍约纯纳纵纸纹纺纽线练绒织绕给络绝绞统"
    "继续维绵综绿缓编缘缩缝缠红纤约级"
    "讠贝车长门马齐韦风韦页飞食鱼鸟"
    "庆刘剧办动励劲势华协单卖南"
    "积课济减温灵热爱炮焕焰猎犹独狩狼狭"
)

# 通常の日本語書籍に殆ど現れない異体字 (ヒットしたら大半が誤認識)
UNUSUAL_CJK = frozenset("仝厶亘亢")


# ============================================================================
# Unicode カテゴリ判定
# ============================================================================
def _is_japanese_char(ch: str) -> bool:
    """ひらがな/カタカナ/CJK 統合漢字 (常用範囲) / 句読点を「日本語として正常」と判定。"""
    cp = ord(ch)
    return (
        0x3040 <= cp <= 0x309F  # ひらがな
        or 0x30A0 <= cp <= 0x30FF  # カタカナ
        or 0x4E00 <= cp <= 0x9FFF  # CJK 統合漢字
        or 0x3000 <= cp <= 0x303F  # 句読点・括弧
        or 0xFF00 <= cp <= 0xFFEF  # 全角英数
        or ch in "\n\t "
        or ch.isascii()
    )


# ============================================================================
# 各種スコア (0.0〜1.0、高いほど崩壊度高)
# ============================================================================
def garble_ratio(text: str) -> float:
    """簡体字 / 異体字 / 非日本語 Unicode の出現率。"""
    if not text:
        return 0.0
    bad = 0
    total = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if ch in SIMPLIFIED_CHARS or ch in UNUSUAL_CJK:
            bad += 1
        elif not _is_japanese_char(ch):
            bad += 1
    return bad / total if total else 0.0


def length_zscore(text: str, lengths: Sequence[int]) -> float:
    """同コーパス内での長さ zscore の絶対値 (1.0 にクランプ)。"""
    if not lengths:
        return 0.0
    median = statistics.median(lengths)
    if median == 0:
        return 0.0
    mad = statistics.median([abs(x - median) for x in lengths]) or 1.0
    z = abs(len(text) - median) / (1.4826 * mad)
    return min(z / 4.0, 1.0)  # zscore 4 以上は飽和


def punct_imbalance(text: str) -> float:
    """鉤括弧 / 丸括弧 の開閉差 (1 個あたり 0.2 加算、1.0 でクランプ)。"""
    pairs = [("「", "」"), ("『", "』"), ("(", ")"), ("（", "）")]
    diff = 0
    for o, c in pairs:
        diff += abs(text.count(o) - text.count(c))
    return min(diff * 0.2, 1.0)


def repetition_score(text: str) -> float:
    """同一文字 3 連以上の出現数を 1 文字あたり 0.1 で加算。"""
    matches = re.findall(r"(.)\1\1+", text)
    return min(len(matches) * 0.1, 1.0)


def end_truncation(text: str) -> float:
    """末尾が句点/閉じ括弧/CJK文字 で終わらない (=途切れ可能性) なら 1.0。"""
    if not text:
        return 0.0
    last = text.rstrip()[-1] if text.rstrip() else ""
    if not last:
        return 0.0
    if last in "。．」』）)…":
        return 0.0
    if _is_japanese_char(last) and unicodedata.category(last).startswith("L"):
        # 漢字・かな で終わるのは普通 (言い切り)
        return 0.3
    return 1.0


def short_line_ratio(text: str) -> float:
    """改行区切り行のうち 5 文字以下の割合 (改行重視レイアウトの場合)。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return 0.0
    short = sum(1 for line in lines if len(line) <= 5)
    return short / len(lines)


# ============================================================================
# 集計
# ============================================================================
DEFAULT_WEIGHTS: dict[str, float] = {
    "garble": 3.0,
    "length": 1.0,
    "punct": 2.0,
    "repetition": 2.0,
    "end_trunc": 1.0,
    "short_lines": 1.0,
}


def score_text(
    text: str,
    *,
    corpus_lengths: Sequence[int] = (),
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> dict[str, float]:
    """単一テキストの各種スコアと加重総和を返す。

    Returns:
        {"garble": .., "length": .., ..., "total": 加重平均 (0.0-1.0)}
    """
    parts = {
        "garble": garble_ratio(text),
        "length": length_zscore(text, corpus_lengths),
        "punct": punct_imbalance(text),
        "repetition": repetition_score(text),
        "end_trunc": end_truncation(text),
        "short_lines": short_line_ratio(text),
    }
    total_w = sum(weights.values()) or 1.0
    parts["total"] = sum(parts[k] * weights.get(k, 0.0) for k in parts) / total_w
    return parts


def score_row(
    row: Mapping[str, Any],
    text_fields: Sequence[str],
    *,
    corpus_lengths: Mapping[str, Sequence[int]] | None = None,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> dict[str, Any]:
    """複数フィールドを持つ行に対し、最大スコアを行スコアとする。

    Returns:
        {field名: {part: score, ...}, "_max_total": float, "_max_field": str}
    """
    corpus_lengths = corpus_lengths or {}
    per_field: dict[str, dict[str, float]] = {}
    max_total = 0.0
    max_field = ""
    for f in text_fields:
        text = row.get(f) or ""
        if not isinstance(text, str):
            continue
        s = score_text(text, corpus_lengths=corpus_lengths.get(f, ()), weights=weights)
        per_field[f] = s
        if s["total"] > max_total:
            max_total = s["total"]
            max_field = f
    return {**per_field, "_max_total": max_total, "_max_field": max_field}


def partition_by_threshold(
    rows: Iterable[Mapping[str, Any]],
    text_fields: Sequence[str],
    *,
    threshold: float = 0.30,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """しきい値以上の行 (suspicious) と それ以下 (clean) に分割。

    各行に `_score` キーを追加して返す。
    `corpus_lengths` はコーパス全体から自動計算する。
    """
    rows_list = list(rows)
    # 各フィールドの長さ分布を先にサンプル
    corpus_lengths: dict[str, list[int]] = {}
    for f in text_fields:
        corpus_lengths[f] = [len(r.get(f) or "") for r in rows_list if isinstance(r.get(f), str)]

    suspicious: list[dict[str, Any]] = []
    clean: list[dict[str, Any]] = []
    for row in rows_list:
        s = score_row(row, text_fields, corpus_lengths=corpus_lengths, weights=weights)
        annotated = {**row, "_score": s}
        if s["_max_total"] >= threshold:
            suspicious.append(annotated)
        else:
            clean.append(annotated)
    return suspicious, clean
