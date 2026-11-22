"""book2md 共通部品(標準ライブラリのみ)"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

PGX_PREFIX = "PGX_"
MARGIN_RATIO = 0.12  # 余白帯(上下)の高さ比。nombre と layout で共通

STATUS_OK = "ok"  # 欠けなし → MD 出力
STATUS_OK_UNCHECKED = "ok_unchecked"  # ノンブルが読めず判定不能だが OCR した
STATUS_MISSING = "missing"  # 欠けあり → PGX_、OCR しない
STATUS_UNCERTAIN_SKIPPED = "uncertain_skipped"  # 判定不能で --on-uncertain skip
STATUS_CHECKED_OK = "checked_ok"  # 検査のみ: 欠けなし
STATUS_CHECKED_UNCERTAIN = "checked_uncertain"  # 検査のみ: ノンブルが読めず判定不能
STATUS_FAILED = "failed"
STATUS_SKIPPED_DONE = "skipped_done"  # Air 側: MD 済みで今回は何もしない
STATUS_SKIPPED_PGX = "skipped_pgx"  # PGX_ 始まりの入力を飛ばした


def job_id_for(path: str | Path) -> str:
    """PDF の中身の sha256 先頭 12 桁(1 MiB ずつ読む)。名前を変えても同じ ID。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:12]


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """<path>.tmp に書いて os.replace する。親ディレクトリは作る。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def atomic_write_text(path: str | Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def backup_existing(dest, backup_dir, new_data: bytes) -> Path | None:
    """dest が既にあり、中身が new_data と違うときだけ、backup_dir へ移して移動先を返す。
    dest が無い、または中身が同じなら何もせず None。既存のバックアップは上書きしない。"""
    dest = Path(dest)
    if not dest.is_file():
        return None
    try:
        if dest.read_bytes() == new_data:
            return None
    except OSError:
        return None
    bdir = Path(backup_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = bdir / f"{dest.stem}.{stamp}{dest.suffix}"
    n = 1
    while target.exists():
        n += 1
        target = bdir / f"{dest.stem}.{stamp}_{n}{dest.suffix}"
    os.replace(dest, target)
    return target


def atomic_write_json(path: str | Path, obj) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def read_json(path: str | Path, default=None):
    """無い/壊れている場合は default を返す。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def pgx_name(filename: str) -> str:
    return PGX_PREFIX + filename
