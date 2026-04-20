"""OCR 後の LLM 校正辞書の管理とマージを行うユーティリティ。

想定ワークフロー:

    OCR → 正規化 (fix_ocr) → LLM 校正辞書で差分適用 → 構造化データ

校正辞書は各プロジェクトが Python モジュールとして管理する:

    # llm_corrections_days_001_010.py
    CORRECTIONS: dict[tuple[int, int], dict[str, str]] = {
        (1, 1): {"lead": "...", "leadText": "..."},
        (1, 3): {"lead": "..."},  # 部分指定も OK
    }

キーの型はプロジェクト依存 (tuple / str / int どれでも OK)。
値は dict[str, str] で、更新するフィールドのみ含める (idempotent)。

本モジュールは:

- 複数モジュールのマージロード
- バリデーション (空文字・JSON 配列形式等)
- apply_corrections(rows, corrections, apply_row) で行単位 callback 適用

DB 投入 / ファイル書き出しなど実際の書き込みは呼び出し側が callback で実装する
(本モジュールは I/O 非依存)。
"""
from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Hashable, Iterable, Mapping
from pathlib import Path
from typing import Any

# 型エイリアス: キーはプロジェクト依存 (tuple/str/int)
CorrectionKey = Hashable
CorrectionValue = dict[str, str]
Corrections = dict[CorrectionKey, CorrectionValue]


class CorrectionError(ValueError):
    """校正辞書に不整合がある場合に送出する例外。"""


def load_module(path: Path, attr: str = "CORRECTIONS") -> Corrections:
    """Python ファイルから CORRECTIONS を読み込む。

    ファイルは import システムに登録しないため、モジュール名の衝突を気にしなくて良い。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise CorrectionError(f"module spec を作成できません: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = getattr(mod, attr, None)
    if not isinstance(data, dict):
        raise CorrectionError(f"{path}: {attr} が dict ではありません")
    return dict(data)


def load_merged(paths: Iterable[Path], attr: str = "CORRECTIONS") -> Corrections:
    """複数の校正ファイルを順にロードしてマージする (後勝ち)。"""
    merged: Corrections = {}
    for p in paths:
        corr = load_module(Path(p), attr=attr)
        merged.update(corr)
    return merged


def validate(
    corrections: Corrections,
    *,
    allowed_fields: set[str] | None = None,
    json_array_fields: set[str] | None = None,
    min_length: int = 1,
) -> None:
    """校正辞書の構造的妥当性をチェック。

    - 値は dict で、許可フィールド以外を含まない (allowed_fields 指定時)
    - 文字列値が min_length 以上
    - json_array_fields に指定したキーは JSON 配列文字列であること
    """
    json_array_fields = json_array_fields or set()
    for key, entry in corrections.items():
        if not isinstance(entry, dict):
            raise CorrectionError(f"{key}: entry が dict ではありません")
        for field, value in entry.items():
            if allowed_fields is not None and field not in allowed_fields:
                raise CorrectionError(f"{key}.{field}: 許可されていないフィールド")
            if not isinstance(value, str):
                raise CorrectionError(f"{key}.{field}: 値が str ではありません")
            if len(value.strip()) < min_length:
                raise CorrectionError(f"{key}.{field}: 値が短すぎます")
            if field in json_array_fields:
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as e:
                    raise CorrectionError(f"{key}.{field}: JSON としてパース不可 ({e})") from e
                if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
                    raise CorrectionError(f"{key}.{field}: JSON 文字列配列であるべき")


def apply_corrections(
    rows: Iterable[Mapping[str, Any]],
    corrections: Corrections,
    *,
    key_fn: Callable[[Mapping[str, Any]], CorrectionKey],
    apply_row: Callable[[dict[str, Any], CorrectionValue], None] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """行データに校正辞書を適用する。

    Args:
        rows: データ行 (dict-like)。
        corrections: 校正辞書。
        key_fn: 行から CorrectionKey を抽出する関数。
        apply_row: 変更を実行する callback。
            dry_run=True の場合は呼び出されない (件数集計のみ)。
            None の場合は in-place で mapping を更新する (デフォルト挙動)。
        dry_run: 副作用なしで件数だけ返す。

    Returns:
        {"total": 行数, "matched": マッチ件数, "applied": 実適用件数}
    """
    total = matched = applied = 0
    for row in rows:
        total += 1
        key = key_fn(row)
        patch = corrections.get(key)
        if not patch:
            continue
        matched += 1
        if dry_run:
            continue
        if apply_row is None:
            if not isinstance(row, dict):
                raise CorrectionError(
                    f"apply_row を指定しないときは row が dict である必要があります: {type(row)}"
                )
            row.update(patch)
        else:
            apply_row(dict(row), patch)
        applied += 1
    return {"total": total, "matched": matched, "applied": applied}


def diff_summary(
    before: Mapping[CorrectionKey, Mapping[str, Any]],
    after: Corrections,
) -> dict[str, int]:
    """before と after を比較して変更セル数を集計する。"""
    fields_changed: dict[str, int] = {}
    for key, patch in after.items():
        original = before.get(key, {})
        for field, new_val in patch.items():
            old_val = original.get(field)
            if old_val != new_val:
                fields_changed[field] = fields_changed.get(field, 0) + 1
    return fields_changed
