# 書籍単位の後校正ワークフロー (sheets.yaml + xlsx-correct-book)

1 シート単位の `xlsx-correct` を書籍単位に拡張した版。**書籍 1 冊分の複数シートを宣言的に一括校正**できる。

---

## いつ使うか

- 1 書籍に複数シートがあり、シートごとにキー構造が違う
- 複数書籍を同じパターンで校正していくので、**コマンドを毎回書き換えたくない**
- シート毎に校正辞書を分割管理したい (辞書の増加に備える)

---

## ディレクトリレイアウト規約

```
_books/<project>/<book_name>/
├── sheets.yaml               # 書籍メタデータ (必須)
├── corrections/              # 校正辞書ルート (sheets.yaml で変更可)
│   ├── Sheet1/
│   │   ├── llm_corrections_001.py
│   │   └── llm_corrections_002.py
│   ├── 引き寄せコア/
│   │   └── llm_corrections_001.py
│   ├── 個人サイクル/
│   │   └── llm_corrections_001.py
│   └── 宇宙サイクル/
│       └── llm_corrections_001.py
└── ...
```

**規約のポイント**
- 校正辞書は **シート名をそのままサブディレクトリ名** に使う
- 1 シートの辞書は複数ファイルに分割 OK (例: 章ごと、担当者ごと)
- ファイル名は `llm_corrections_*.py` (glob で探索)

---

## sheets.yaml 形式

```yaml
xlsx: ../引き寄せ数秘術の教科書_水谷奏音.xlsx   # 相対パスは sheets.yaml 基準
corrections_dir: corrections                    # デフォルトは "corrections"

sheets:
  - name: Sheet1
    key_cols: [LifePathNumber]   # 行キー列 (タプル化される)
    enabled: true

  - name: 引き寄せコア
    key_cols: [Type, Number]
    enabled: true

  # 校正不要シートは enabled: false で明示的にスキップ
  - name: 基本ナンバー
    enabled: false

  - name: 相性表
    enabled: false
```

**フィールド**
| キー | 必須 | 説明 |
|---|---|---|
| `name` | ✓ | シート名 (対象 XLSX 内と一致) |
| `key_cols` | enabled=true なら ✓ | 行キー列のリスト |
| `enabled` | - | true/false (デフォルト true) |
| `glob` | - | 辞書ファイル glob (デフォルト `llm_corrections_*.py`) |
| `corrections_subdir` | - | サブディレクトリ名 (デフォルトは `name` と同じ) |

---

## CLI

```bash
# 全 enabled シートをドライラン (件数・diff 統計のみ)
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml --dry-run

# シート毎の比較 XLSX を出力してレビュー
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml \
    --preview-dir previews/ --dry-run

# 本適用 (sheets.yaml の xlsx を上書き)
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml

# 別ファイルに保存
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml --out book.corrected.xlsx
```

### 出力例

```
# 書籍: /.../引き寄せ数秘術の教科書_水谷奏音.xlsx
# corrections_dir: /.../corrections
# 対象シート: 4/10 (enabled)
  ✓ Sheet1  key_cols=[LifePathNumber]
  ✓ 引き寄せコア  key_cols=[Type,Number]
  ✓ 個人サイクル  key_cols=[Type,Number]
  ✓ 宇宙サイクル  key_cols=[Type,Number]
  - 基本ナンバー  key_cols=[Number]
  - 相性表
  ...

sheet            files entries matched cells notes
--------------------------------------------------
Sheet1               3      12      12    48 applied=12, fields=['リード本文','長所本文',...]
引き寄せコア         2      36      36    95 applied=36, fields=['Title1','Body',...]
個人サイクル         1      27      27    48
宇宙サイクル         1       9       9    18

# 合計: 4 シート処理 / skipped 0
#        matched 84, cells_changed 209
```

---

## Python API

```python
from ocr_toolkit.book_config import load_book_config
from ocr_toolkit.xlsx_corrections import apply_book

config = load_book_config("sheets.yaml")

# ドライラン
reports = apply_book(config, dry_run=True)
for sheet_name, r in reports.items():
    if sheet_name == "_total":
        continue
    if not r.get("skipped"):
        print(f"{sheet_name}: {r['cells_changed']} cells")

# 本適用 + preview 同時出力
apply_book(
    config,
    preview_dir="previews/",
    out_path="book.corrected.xlsx",
)
```

---

## 校正辞書の LLM 生成フロー (推奨)

複数シートを効率よく埋めるための標準ワークフロー。

### 1. シート毎に現在値を JSON 出力

```python
from ocr_toolkit.xlsx_corrections import load_sheet_rows

_, rows = load_sheet_rows("book.xlsx", "引き寄せコア")
import json
with open("tmp/引き寄せコア.current.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
```

### 2. LLM に校正を依頼

Claude にシート毎のコンテキストと `current.json` を渡し、**`CORRECTIONS = {...}` 形式の Python モジュール** で返させる。プロンプトの要点:

- キー形式は `key_cols` のタプル (例: `("Destiny", 1)`)
- 修正するフィールドだけ含める (idempotent)
- 原文の意味を変えず、OCR 誤字のみ直す
- 明らかに判別不能な文字は `[要確認]` 等でマーク

### 3. 生成結果を `corrections/<sheet>/llm_corrections_NNN.py` に保存

```python
# corrections/引き寄せコア/llm_corrections_001.py
CORRECTIONS = {
    ("Destiny", 1): {
        "Title1": "リーダーシップを発揮して周りを引っ張っていきたい",
        "Title2": "新しいことを始めたい、そしてそれを突き進めたい",
        "Body": "...",
    },
    ...
}
```

### 4. dry-run → preview → 本適用

```bash
# 辞書のバリデーション (空文字・許可外フィールド等を早期検出)
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml --dry-run

# 比較 XLSX で目視レビュー
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml \
    --preview-dir previews/ --dry-run
open previews/引き寄せコア_diff.xlsx

# 本適用
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml
```

---

## 複数書籍を順次処理する

シェルでループ:

```bash
for book in _books/*/*/sheets.yaml; do
  python -m ocr_toolkit.cli xlsx-correct-book "$book" --dry-run
done
```

Python:

```python
from pathlib import Path
from ocr_toolkit.book_config import load_book_config
from ocr_toolkit.xlsx_corrections import apply_book

for yaml_path in Path("_books").rglob("sheets.yaml"):
    config = load_book_config(yaml_path)
    reports = apply_book(config, dry_run=True)
    total = reports["_total"]
    print(f"{config.xlsx.name}: {total['cells_changed']} cells changeable")
```

---

## 設計方針

- **sheets.yaml は書籍ごとに独立**: 書籍横断的な共通設定は持たない (シート構造が違うため)
- **辞書サブディレクトリ == シート名**: ファイル探索とレビュー時の発見性を優先
- **enabled=false は省略せず明示**: 「校正対象外」もレビュー対象として残す
- **1 書籍 = 1 openpyxl wb**: 複数シート処理時に `load_workbook`/`save` を 1 回に抑える
- **相対パス解決**: `xlsx` / `corrections_dir` は sheets.yaml 基準で解決 (cwd 非依存)
