"""書籍メタデータ sheets.yaml のロードとデータクラス。

書籍単位で複数シートを一括校正するための宣言ファイル形式:

    # <book_dir>/sheets.yaml
    xlsx: ../book.xlsx
    corrections_dir: corrections

    sheets:
      - name: Sheet1
        key_cols: [LifePathNumber]
        enabled: true
      - name: 引き寄せコア
        key_cols: [Type, Number]
        enabled: true
      - name: 基本ナンバー
        key_cols: [Number]
        enabled: false   # 校正不要

相対パスは yaml ファイルのあるディレクトリを基準に解決する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "book_config.py は PyYAML に依存します。`pip install pyyaml` してください。"
    ) from e


@dataclass
class SheetConfig:
    """1 シートの校正設定。"""
    name: str
    key_cols: list[str] = field(default_factory=list)
    enabled: bool = True
    glob: str = "llm_corrections_*.py"
    corrections_subdir: str | None = None  # デフォルトは name を使う


@dataclass
class BookConfig:
    """書籍単位の校正設定。"""
    xlsx: Path
    corrections_dir: Path
    sheets: list[SheetConfig]
    base_dir: Path  # sheets.yaml の配置ディレクトリ

    def enabled_sheets(self) -> list[SheetConfig]:
        return [s for s in self.sheets if s.enabled]

    def sheet_corrections_dir(self, sheet: SheetConfig) -> Path:
        """シート用の校正辞書ディレクトリパス。"""
        subdir = sheet.corrections_subdir or sheet.name
        return self.corrections_dir / subdir


def load_book_config(yaml_path: str | Path) -> BookConfig:
    """sheets.yaml を読んで BookConfig を返す。

    Args:
        yaml_path: sheets.yaml のパス。

    Returns:
        BookConfig。
    """
    yaml_path = Path(yaml_path).resolve()
    if not yaml_path.exists():
        raise FileNotFoundError(yaml_path)

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    base_dir = yaml_path.parent

    if "xlsx" not in data:
        raise ValueError(f"{yaml_path}: 'xlsx' が必要です")
    xlsx = _resolve(base_dir, data["xlsx"])
    corrections_dir = _resolve(base_dir, data.get("corrections_dir", "corrections"))

    raw_sheets = data.get("sheets") or []
    if not raw_sheets:
        raise ValueError(f"{yaml_path}: 'sheets' が空です")

    sheets: list[SheetConfig] = []
    for idx, entry in enumerate(raw_sheets):
        if "name" not in entry:
            raise ValueError(f"{yaml_path}: sheets[{idx}] に 'name' がありません")
        sheets.append(SheetConfig(
            name=str(entry["name"]),
            key_cols=list(entry.get("key_cols") or []),
            enabled=bool(entry.get("enabled", True)),
            glob=str(entry.get("glob", "llm_corrections_*.py")),
            corrections_subdir=entry.get("corrections_subdir"),
        ))

    return BookConfig(
        xlsx=xlsx,
        corrections_dir=corrections_dir,
        sheets=sheets,
        base_dir=base_dir,
    )


def _resolve(base: Path, p: str | Path) -> Path:
    """相対パスを base 基準で解決する (絶対パスはそのまま)。"""
    pp = Path(p)
    return pp if pp.is_absolute() else (base / pp).resolve()


__all__ = [
    "SheetConfig",
    "BookConfig",
    "load_book_config",
]
