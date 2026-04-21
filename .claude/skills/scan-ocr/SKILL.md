---
name: scan-ocr
description: 書籍スキャンPDFや画像を ScanToXlsxStarter パイプラインで高精度日本語OCRする。「この本をOCR」「スキャンPDFをXLSX化」「日本語スキャンの精度を上げたい」等の要求時に使う。PaddleOCR(PP-OCRv5)+ プロジェクト固有の誤字辞書でTesseractより劇的に高精度。
---

# scan-ocr (ScanToXlsxStarter toolkit)

書籍・文書スキャンのPDFや画像を、**PaddleOCR(PP-OCRv5)** と **OCR誤字辞書** を使って日本語OCRするためのスキル。

## いつ使うか

- スキャンPDF / 画像 → テキスト抽出したい
- 日本語で Tesseract の精度に不満がある
- 大量ページを並列処理したい(書籍 366日分など)
- OCR結果 → 構造化データ(XLSX/JSON)を作りたい

## 前提

- macOS Apple Silicon(M系)
- Homebrew Python 3.13
- `pdftoppm` (poppler)
- `~/Documents/dsgarageScript/ScanToXlsxStarter/` にツールキットが配置済み

## 使い方

### 1. 初回セットアップ(venv作成)

```bash
cd ~/Documents/dsgarageScript/ScanToXlsxStarter
./setup.sh
```

venv は `.venv_paddleocr/` に作られる。`paddlepaddle==3.2.1` + `paddleocr[doc-parser]` が入る。

### 2. ワンショット実行(config.yaml)

1. プロジェクトディレクトリに `config.yaml` を用意(`configs/example.yaml` を参照)。
2. 実行:

```bash
~/Documents/dsgarageScript/ScanToXlsxStarter/.venv_paddleocr/bin/python \
  -m ocr_toolkit.cli run config.yaml
```

`config.yaml` の場所を基準に `images/`, `ocr/` が作られる。

### 3. 個別コマンド

- PDF→PNG化:
  `python -m ocr_toolkit.cli pdf2png input.pdf out/images/ --dpi 300`
- 画像ディレクトリを並列OCR:
  `python -m ocr_toolkit.cli ocr out/images/ out/ocr/`
- サーバ版モデル(高精度・低速):
  `python -m ocr_toolkit.cli ocr ... --server`

### 4. Pythonから使う

```python
from ocr_toolkit import BatchOCR, fix_ocr, pdf_to_png

pdf_to_png("book.pdf", "images/", dpi=300)

runner = BatchOCR(lang="japan", workers=4, use_mobile=True)
runner.run("images/", "ocr/")

# プロジェクト固有の誤字はextra_fixesで追加可能
text = open("ocr/page-001.txt").read()
cleaned = fix_ocr(text, extra_fixes={"半的感覚": "美的感覚"})
```

### 5. 完成 XLSX の後校正

既に構造化済みの XLSX を **シート単位で LLM 校正辞書で後校正** できる (`ocr_toolkit.xlsx_corrections`)。

```bash
# ドライランで件数/差分確認
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --dry-run

# 比較 XLSX を出力してレビュー
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --preview preview.xlsx --dry-run

# 本適用 (変更セルは薄黄でハイライト)
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --out book.corrected.xlsx
```

校正辞書は `CORRECTIONS = {(key_tuple): {field: "修正後"}}` 形式の Python モジュールで、シート毎に 1 ファイル作る運用。詳細は `examples/xlsx_corrections_workflow.md`。

## 精度の目安

Tesseract vs PaddleOCR(日本語書籍スキャン300dpi)の誤字:

| | Tesseract | PaddleOCR(PP-OCRv5) |
|---|---|---|
| 「裏側」 | `音側` | `裏側` ✓ |
| 「相手」 | `相隆` | `相手` ✓ |
| 「皮肉」 | `皮内` | `皮肉` ✓ |
| 「見透かされ」 | `見穫かきれ` | `見透かされ` ✓ |

残る誤字のほとんどは `fix_ocr()` の辞書で吸収できる(例: 促音「つ」→「っ」、カタカナ「一」→「ー」、夕→タ)。

## 高速化のコツ

- `use_mobile=True`(PP-OCRv5_mobile)で server版より数倍速い
- `workers=4-6` が Apple Silicon で体感ベスト(メモリに注意)
- 画像クロップを事前に小さく(`crop_regions` 関数)しておくと更に高速
- 既存 `.txt` は自動スキップするため、落ちても途中再開できる

## トラブル

- **`pip install` で SSL エラー**: Python 3.11 の certifi バンドルが古い。`setup.sh` は Python 3.13 を使う
- **Paddle モデル DL が遅い**: `~/.paddlex/` にキャッシュされるので2回目以降は速い
- **OOM**: `workers` を下げる(2-3)
