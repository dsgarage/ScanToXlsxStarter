# 完成 XLSX の後校正ワークフロー (xlsx_corrections)

既に構造化済み・ビルド済みの XLSX に対して、LLM 校正辞書で **シート単位の誤字を後から差し替える** 手順。

`ocr_toolkit.corrections` が rows (dict リスト) ベースで DB 投入前の校正を担当するのに対し、`ocr_toolkit.xlsx_corrections` は **成果物 XLSX を保持したまま** 誤字を差し替えるユースケースを担当する。

---

## いつ使うか

- OCR 誤字が残った完成 XLSX を手元に抱えていて、DB 投入前に XLSX レベルで品質チェックしたい
- 複数シートで構造が違い、シート単位で独立に校正を当てたい
- 人間レビュー用に「変更前 / 変更後」比較 XLSX が欲しい

---

## 校正辞書の形式

1 シート = 1 校正辞書ファイル。ファイル名は `llm_corrections_<sheet>_<batch>.py` の慣例。

```python
# corrections/llm_corrections_sheet1_001.py
CORRECTIONS = {
    # キー: key_fields で指定した列値のタプル
    # (単一キーの場合はタプルでなく単値でも OK)
    ("Destiny", 1): {"Title1": "修正後テキスト", "Body": "..."},
    ("Soul", 11):   {"Title1": "..."},
}
```

- **キーの型**: `key_fields=("Type","Number")` を指定したなら `(str, int)` のタプル
- **値**: `dict[列名, 修正後テキスト]` (変更する列のみ含めれば OK)
- 複数ファイルに分割可能。`load_merged([...])` で順にマージ (後勝ち)

---

## CLI から

### 1. ドライラン (件数だけ確認)

```bash
python -m ocr_toolkit.cli xlsx-correct \
  book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number \
  --dry-run
```

出力例:
```
# 校正辞書: 3 ファイル
# エントリ数: 45
# 適用結果:
  rows          : 36
  matched       : 42
  applied       : 0
  cells_changed : 118
  fields        : {'Title1': 42, 'Body': 38, 'Title2': 38}
  (dry-run: 保存は行っていません)
```

`matched` に対して `unmatched_keys` があれば、辞書側のキーが行データに無いことを示す (キー名のタイプミスなど)。

### 2. 比較 XLSX プレビューを出力

```bash
python -m ocr_toolkit.cli xlsx-correct \
  book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number \
  --preview preview.xlsx \
  --dry-run
```

`preview.xlsx` に「元 / 校正後」が並んだハイライト付き XLSX が生成される。Excel で目視レビュー後、本適用に進む。

### 3. 本適用 (in-place 上書き)

```bash
python -m ocr_toolkit.cli xlsx-correct \
  book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number \
  --out book.corrected.xlsx
```

`--out` 未指定なら `book.xlsx` を上書き。`--no-highlight` で変更セルの薄黄塗りを無効化できる。

---

## Python API から

```python
from pathlib import Path
from ocr_toolkit import load_merged
from ocr_toolkit.xlsx_corrections import apply_to_xlsx, preview_xlsx_corrections

corrections = load_merged(Path("corrections").glob("llm_corrections_sheet1_*.py"))

# ドライランで件数確認
stats = apply_to_xlsx(
    "book.xlsx", "Sheet1", corrections,
    key_fields=("Type", "Number"),
    dry_run=True,
)
print(stats)  # {"rows":36, "matched":42, "applied":0, "cells_changed":118, ...}

# 比較 XLSX
preview_xlsx_corrections(
    "book.xlsx", "Sheet1", corrections,
    key_fields=("Type", "Number"),
    output="preview.xlsx",
)

# 本適用
apply_to_xlsx(
    "book.xlsx", "Sheet1", corrections,
    key_fields=("Type", "Number"),
    out_path="book.corrected.xlsx",
    highlight=True,
)
```

---

## 複数シートを順次校正する

シート毎に校正辞書ディレクトリと `key_fields` を分ける。

```python
SHEETS = [
    ("Sheet1",       ("LifePathNumber",),          "corrections/sheet1"),
    ("引き寄せコア", ("Type", "Number"),           "corrections/attraction"),
    ("個人サイクル", ("Type", "Number"),           "corrections/cycles_personal"),
    ("宇宙サイクル", ("Type", "Number"),           "corrections/cycles_universal"),
]

for sheet, key_fields, corr_dir in SHEETS:
    corrections = load_merged(Path(corr_dir).glob("llm_corrections_*.py"))
    summary = apply_to_xlsx(
        "book.xlsx", sheet, corrections,
        key_fields=key_fields,
    )
    print(f"{sheet}: {summary['cells_changed']} cells changed")
```

---

## バリデーション

`apply_to_xlsx` は自動で以下をチェックする:

- `key_fields` の列名がヘッダに存在するか
- 校正辞書の値がヘッダに存在する列名か (`allowed_fields` 引数で上書き可能)
- 空文字や辞書以外の値が混ざっていないか (`corrections.validate` と同じ)

問題があれば `CorrectionError` が早期に送出されるため、壊れたテキストで XLSX を上書きする事故を防げる。

---

## 設計方針

- **rows ベース API とは完全に独立**: 既存の `corrections.apply_corrections` は無変更
- **openpyxl レイヤのみ差分更新**: シート構造や他セルのスタイルは触らない
- **ハイライト**: `preview.py` の `FILL_CHANGED` (薄黄) を再利用してレビューで色が一致
- **1 シート = 1 辞書**: シート毎にキー構造が違うため、辞書ファイルもシート毎に分離するのを推奨
