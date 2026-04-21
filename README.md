# ScanToXlsxStarter

**書籍スキャン・画像 → 高精度日本語OCR → 構造化データ** を1コマンドで。

macOS (Apple Silicon) 向けに最適化された、**PaddleOCR (PP-OCRv5) + 誤字辞書** の軽量パイプライン。Tesseract より圧倒的に精度が高く、並列化で高速。

```
  λx. PDF → PNG → crop → OCR → fix → structured data
```

---

## 特長

| | 内容 |
|---|---|
| **高精度日本語OCR** | PaddleOCR `PP-OCRv5_mobile/server` を採用。Tesseractより桁違いに誤字が少ない |
| **高速** | `ProcessPoolExecutor` + mobileモデルで 1画像あたり1秒以下(M系 Mac, 4並列) |
| **再開可能** | 既存のテキスト出力は自動スキップ。途中で落ちても続きから再開 |
| **誤字辞書** | 日本語OCRで頻出する誤字(「夕→タ」「一→ー」「つ→っ」など)を共通辞書で一括修正。プロジェクト固有の辞書を差し込み可 |
| **汎用CLI** | `pdf2png` / `ocr` / `run` の3サブコマンド |
| **Claude Code スキル対応** | `.claude/skills/scan-ocr/SKILL.md` を同梱。Claude から自然言語で呼び出せる |

## 比較: Tesseract vs PaddleOCR(日本語書籍スキャン300dpi)

| 正しい文字 | Tesseract | PaddleOCR ✓ |
|---|---|---|
| 裏側 | `音側` ✗ | `裏側` |
| 相手 | `相隆` ✗ | `相手` |
| 皮肉 | `皮内` ✗ | `皮肉` |
| 見透かされ | `見穫かきれ` ✗ | `見透かされ` |
| 気遣う | `気道う` ✗ | `気遣う` |

PaddleOCR出力に残るわずかな誤字は `fix_ocr()` で吸収できる。

---

## インストール

前提:
- macOS (Apple Silicon 推奨)
- Homebrew で Python 3.13 と poppler:
  ```bash
  brew install python@3.13 poppler
  ```

リポジトリ取得と環境構築:

```bash
git clone https://github.com/dsgarage/ScanToXlsxStarter.git
cd ScanToXlsxStarter
./setup.sh
```

`setup.sh` は `./.venv_paddleocr/` に venv を作成し、`paddlepaddle==3.2.1` と `paddleocr[doc-parser]` をインストールします(CPU版 / Apple Silicon 対応)。

> 💡 `PREFIX=/path/to/venv ./setup.sh` で任意の場所に venv を作れます。

---

## 使い方

### A. CLI(手軽)

```bash
# PDF → PNG
python -m ocr_toolkit.cli pdf2png book.pdf out/images/ --dpi 300

# 画像ディレクトリ → OCRテキスト(並列)
python -m ocr_toolkit.cli ocr out/images/ out/ocr/

# config.yaml で一括実行
python -m ocr_toolkit.cli run configs/my_project.yaml
```

venv を都度activateしたくない場合は、直接パスで呼び出します:

```bash
~/Documents/dsgarageScript/ScanToXlsxStarter/.venv_paddleocr/bin/python \
  -m ocr_toolkit.cli ocr images/ ocr/
```

### B. config.yaml で宣言的に

```yaml
# configs/my_project.yaml
pdf:
  path: input.pdf
  first_page: 1
  last_page: null
  dpi: 300

images_dir: images
ocr_dir: ocr

ocr:
  lang: japan
  workers: 4
  use_mobile: true
```

```bash
python -m ocr_toolkit.cli run configs/my_project.yaml
```

### C. Python API

```python
from ocr_toolkit import BatchOCR, fix_ocr, pdf_to_png, crop_regions

pdf_to_png("book.pdf", "images/", dpi=300)

# 領域クロップ(1枚から複数領域を切り出す場合)
crop_regions(
    "images/page-001.png",
    regions={
        "sidebar": (0, 0, 520, 2200),
        "body":    (520, 0, 1644, 2200),
    },
    out_dir="crops/",
    stem="p001",
)

# 並列OCR
runner = BatchOCR(lang="japan", workers=4, use_mobile=True)
runner.run("crops/", "ocr/")

# OCR誤字を修正
raw = open("ocr/p001-body.txt").read()
clean = fix_ocr(raw, extra_fixes={"半的感覚": "美的感覚"})
```

### D. Claude Code スキルとして

`.claude/skills/scan-ocr/SKILL.md` が同梱されています。`~/.claude/skills/scan-ocr/` にシンボリックリンクするか、リポジトリ直下の `.claude/` が自動的に認識されます。

Claude に自然言語で依頼できます:
> *「このPDFを ScanToXlsxStarter でOCRして、XLSX化して」*

### E. OCR 後の LLM 文脈校正パイプライン

`fix_ocr()` の辞書置換で直らない **「文として成立しない」レベルの崩壊** は、Claude Opus の文脈推論で復元します。
v0.3.0 から **suspicion 事前フィルタ** が加わり、LLM に送る前に「機械的に直せる行」を除外できます (トークン消費 ~70% 削減)。

```python
from ocr_toolkit import (
    fix_ocr,                    # 事前の文字列置換
    partition_by_threshold,     # 崩壊スコアで pre-filter (★ v0.3.0)
    load_merged,                # 校正辞書ファイルのマージロード
    validate,                   # 校正辞書の妥当性チェック
    apply_corrections,          # 行データへの校正適用
)
from ocr_toolkit.preview import write_comparison  # 比較 XLSX 生成

# 0) fix_ocr で簡体字/促音/末尾ノイズを機械処理 → suspicion で LLM 対象を抽出
processed = [{**r, "leadText": fix_ocr(r["leadText"])} for r in raw_rows]
suspicious, clean = partition_by_threshold(
    processed, text_fields=("lead", "leadText"), threshold=0.10,
)
# suspicious だけを LLM に投入 (clean は fix_ocr のみで採用)

# 1) 校正辞書を統合
merged = load_merged(["llm_corrections_batch1.py", "llm_corrections_batch2.py"])
validate(merged, allowed_fields={"lead", "leadText"})

# 2) 本番 DB / 出力先に適用 (DB 操作は呼び出し側 callback)
apply_corrections(processed, merged, key_fn=lambda r: (r["month"], r["day"]))

# 3) 比較 XLSX で目視レビュー
write_comparison(output="preview.xlsx", rows=..., fields=("lead", "leadText"))
```

詳細な運用手順 (suspicion 閾値・並列エージェント設定・タイムアウト回避) は [`examples/llm_cleanup_workflow.md`](examples/llm_cleanup_workflow.md) を参照。

---

## ディレクトリ構成

```
ScanToXlsxStarter/
├── .claude/
│   └── skills/
│       └── scan-ocr/
│           └── SKILL.md        # Claude Code スキル定義
├── configs/
│   └── example.yaml            # config.yaml の雛形
├── examples/
│   ├── birthday_bible.md       # 366日分データ化の事例
│   └── llm_cleanup_workflow.md # OCR後のLLM文脈校正ワークフロー
├── ocr_toolkit/
│   ├── __init__.py
│   ├── cli.py                  # サブコマンドCLI
│   ├── pdf_tools.py            # PDF→PNG, crop_regions
│   ├── paddle_ocr.py           # 並列OCRランナー
│   ├── fix_ocr.py              # 誤字辞書 + 正規表現ルール
│   ├── corrections.py          # LLM校正辞書のロード・適用
│   └── preview.py              # 比較XLSXジェネレータ (openpyxl)
├── LICENSE                     # MIT
├── README.md
├── .gitignore
└── setup.sh                    # Apple Silicon 向け自動セットアップ
```

---

## 設計指針

1. **I/O はディレクトリ単位** - 「画像ディレクトリ → OCRテキストディレクトリ」のシンプルなマッピング。再開/差分処理が自明になる。
2. **モデルは ProcessPool のワーカーごとにロード** - 共有メモリ問題を回避し、クラッシュ耐性を上げる。
3. **辞書は文字列置換のみ** - 正規表現辞書は壊れやすいので、確実な誤字のみを収録。プロジェクト固有の置換は呼び出し側で `extra_fixes` 引数に渡す。
4. **CLIと Python API を両立** - 1コマンドで動かしたい人にも、パイプラインに組み込みたい人にも対応。

---

## 精度を上げるコツ

- **DPIは300以上**: 書籍スキャンは300dpiが推奨。解像度が低いと誤字が急増。
- **領域クロップ**: ページ全体を一括OCRせず、セクション毎に切ってから処理すると後段のパースがシンプルに。
- **mobileで速度、serverで精度**: `--server` (CLI) / `use_mobile=False` (API) で server モデル。精度はわずかに上がるが3〜4倍遅い。
- **日本語以外も**: `lang="en"`, `lang="ch"`, `lang="korean"` などに対応(PaddleOCRが対応している全言語)。

---

## トラブルシューティング

| 症状 | 対応 |
|---|---|
| `pip install` で SSL エラー | Python 3.11 の certifi が古い。`setup.sh` は 3.13 を使うので `brew install python@3.13` |
| Paddle モデルダウンロードが遅い | 初回のみ `~/.paddlex/` にキャッシュ。2回目以降は即起動 |
| OOM / ワーカー落ち | `workers=2-3` に下げる |
| 右ページの日付が取れない | 書籍レイアウトによっては左ページにしか日付がないことがある。`left + 1` で補完するロジックを検討 |
| 章扉で日付ジャンプ | ページ→日付マッピングを自動検出するスクリプトを書く(事例参照) |

---

## ロードマップ

- [ ] PaddleOCR-VL(1.5) 対応 (MLX-VLMサーバ経由)
- [ ] config.yamlに領域クロップ定義を書ける様式
- [ ] OCR結果 → JSON/XLSX 変換のジェネリックヘルパ
- [ ] GPU版 paddlepaddle サポート(M系では Metal 未対応)

## ライセンス

[MIT](LICENSE)

## Credits

- [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — コアOCRエンジン
- [poppler](https://poppler.freedesktop.org/) — PDF→PNG変換
