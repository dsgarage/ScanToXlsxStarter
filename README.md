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

### F. 完成 XLSX の後校正 (xlsx_corrections)

既に構造化済みの XLSX に対して、**シート単位で LLM 校正辞書を後から当てる** ユースケース。DB 投入前の XLSX レベル校正や、複数書籍の統一的な後校正基盤として利用します。

```bash
# ドライラン (件数と diff 統計を確認)
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --dry-run

# 比較 XLSX プレビュー
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --preview preview.xlsx --dry-run

# 本適用 (変更セルは薄黄でハイライト)
python -m ocr_toolkit.cli xlsx-correct book.xlsx "Sheet1" corrections/ \
  --key-cols Type,Number --out book.corrected.xlsx
```

```python
from ocr_toolkit import load_merged
from ocr_toolkit.xlsx_corrections import apply_to_xlsx, preview_xlsx_corrections

corrections = load_merged(Path("corrections").glob("llm_corrections_*.py"))
apply_to_xlsx("book.xlsx", "Sheet1", corrections,
              key_fields=("Type", "Number"), out_path="book.corrected.xlsx")
```

詳細は [`examples/xlsx_corrections_workflow.md`](examples/xlsx_corrections_workflow.md) を参照。

### G. 書籍一括校正 (sheets.yaml + xlsx-correct-book)

書籍 1 冊分の複数シートを宣言的に一括校正する。`sheets.yaml` に書籍構造を書くだけで、シート毎にキー構造が違っても 1 コマンドで処理できる。

```yaml
# _books/数秘術/引き寄せ数秘術の教科書_水谷奏音/sheets.yaml
xlsx: ../引き寄せ数秘術の教科書_水谷奏音.xlsx
corrections_dir: corrections

sheets:
  - name: Sheet1
    key_cols: [LifePathNumber]
    enabled: true
  - name: 引き寄せコア
    key_cols: [Type, Number]
    enabled: true
  - name: 相性表
    enabled: false
```

```bash
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml --dry-run
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml --preview-dir previews/ --dry-run
python -m ocr_toolkit.cli xlsx-correct-book sheets.yaml            # 本適用
```

校正辞書は `corrections/<sheet_name>/llm_corrections_*.py` の規約で配置。詳細は [`examples/xlsx_corrections_full_book.md`](examples/xlsx_corrections_full_book.md) 参照。

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
│   ├── birthday_bible.md              # 366日分データ化の事例
│   ├── llm_cleanup_workflow.md        # OCR後のLLM文脈校正ワークフロー (rows ベース)
│   ├── xlsx_corrections_workflow.md   # 完成 XLSX の後校正ワークフロー (1 シート)
│   └── xlsx_corrections_full_book.md  # 書籍単位の一括校正 (sheets.yaml)
├── ocr_toolkit/
│   ├── __init__.py
│   ├── cli.py                  # サブコマンドCLI
│   ├── pdf_tools.py            # PDF→PNG, crop_regions
│   ├── paddle_ocr.py           # 並列OCRランナー
│   ├── fix_ocr.py              # 誤字辞書 + 正規表現ルール
│   ├── corrections.py          # LLM校正辞書のロード・適用 (rows ベース)
│   ├── xlsx_corrections.py     # 完成 XLSX シートの後校正 (openpyxl)
│   ├── book_config.py          # sheets.yaml のロード (書籍一括校正)
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

---

## book2md(ページ欠け検査 → OCR → Markdown)

スキャンした書籍の PDF について、**ページの欠けを先に検査し、欠けが無ければ OCR して、1 冊につき 1 つの Markdown** を作るツールです。Markdown は後で LLM に校正させる前提で、元の PDF のページ番号と印字ページ番号の目印を入れています。

- 本体は `book2md`(Windows などの GPU マシン向け。CPU でも動きます)
- MacBook などから遠隔の Windows を動かす入口が `book2md-remote`(コードの同期・PDF の転送・結果の取得を行います)

### 遠隔の Windows で動かす(MacBook などから)

```bash
# 初回だけ: 遠隔の Windows に実行環境(venv と PaddleOCR)を作る
python3 -m ocr_toolkit.cli book2md-remote "<フォルダ>" --setup

# 以降: フォルダ内の PDF を処理する
python3 -m ocr_toolkit.cli book2md-remote "<フォルダ>"
```

検査だけ先に行いたいときは `--check-only` を付けます。

```bash
python3 -m ocr_toolkit.cli book2md-remote "<フォルダ>" --check-only
```

検査だけなら、欠けがあっても PDF をリネームせず、OCR も Markdown もしません。後で `--check-only` なしで実行すると、検査の結果はキャッシュから使われ、そのまま OCR に進みます。

前提は次のとおりです。

- ssh でパスワードなしに入れること。ホスト名の既定は `winpc` で、`--host` で変えられます
- Windows 側に `uv` と Python 3.11 が入っていること(`--setup` が `uv venv --python 3.11` で環境を作ります)
- 導入先は Windows のホーム直下の `$HOME\book2md`(`venv`・`app`・`inbox`・`work`・`out`)と、モデルのキャッシュ `~\.paddlex` だけです
- `--setup` は `--device {auto,gpu,cpu}` に従って GPU 版または CPU 版の PaddlePaddle を入れます

`--dry-run` を付けると、通信せずに「処理する PDF」「飛ばす PDF」の一覧だけを表示します。

### Windows などで単体で動かす

```bash
python -m ocr_toolkit.cli book2md <PDF またはフォルダ>
```

フォルダを渡したときは、直下の `*.pdf` が対象です。

### 出力物

| ファイル | 内容 |
|---|---|
| `<元の名前>.md` | 1 冊分の Markdown(欠けが無かった本だけ) |
| `<元の名前>.check.json` | ページ欠け検査の詳細(`book2md` は PDF と同じ場所、`book2md-remote` は `_book2md/`) |
| `_book2md/report.txt` / `report.json` / `state.json` | 遠隔の入口が PDF のフォルダに残す、結果一覧と状態(`remote_report.json` は取得した遠隔のレポート) |
| `book2md_report.json` | 単体の `book2md` が残す結果一覧(`--report` で場所を変えられます) |
| `PGX_<元の名前>.pdf` | 欠けのあった PDF のリネーム先。OCR はしません |

Markdown は先頭に YAML のヘッダがあり、本文にはページごとの目印が入ります。ページの目印は `<!-- page: <PDF のページ番号> printed: <印字ページ番号> -->` で、読み取れなかったときの印字番号は `-` です。末尾の `blank` は、OCR で文字が 1 つも見つからなかったページに付きます。同じページを二重にスキャンしていたときは、先のほうのページに `dup-of: <PDF のページ番号>`(重なる後ろのページ)が付き(例: `<!-- page: 147 printed: 149 dup-of: 155 -->`)、本文は両方とも残します。重なりが 1 ページでもあれば、ヘッダに `duplicate_pages: <件数>` が入ります。

```markdown
---
title: "サンプル"
source: "サンプル.pdf"
pdf_pages: 3
page_check: ok
ocr_model: <モデル名>
ocr_device: <デバイス>
generated: <日時>
tool: ocr_toolkit book2md
---

<!-- page: 1 printed: - -->

ダミーの前書きです。

<!-- page: 2 printed: 1 -->

ダミーの本文その 1 です。

<!-- page: 3 printed: 2 -->

ダミーの本文その 2 です。
```

### 結果の状態

| 表示 | 意味 |
|---|---|
| OK | 欠けは見つからず、OCR して Markdown を作った |
| OK(未検査) | ノンブルが読めず判定できなかったが、OCR して Markdown を作った |
| 欠けあり | 欠けが見つかった。PDF を `PGX_` 始まりにリネームし、OCR はしていない |
| 判定不能 | ノンブルが読めず、`--on-uncertain skip` のため OCR を飛ばした |
| 検査OK | `--check-only` で検査し、欠けは見つからなかった(OCR はしていない) |
| 検査不能 | `--check-only` で検査したが、ノンブルが読めず判定できなかった(OCR はしていない) |
| 失敗 | 処理中にエラーが出た(理由は結果一覧に出ます) |
| 済み | (遠隔の入口)Markdown が既にあり、今回は何もしなかった |
| PGX済 | 入力が `PGX_` 始まりなので飛ばした(`--include-pgx` で処理します) |

### 判定の規則と限界

各ページの上下の余白からノンブル(印字ページ番号)を読み取り、PDF のページ番号との差が途中で 2 ページ以上減ったときに「欠けあり」とします。1 ページだけの欠けは、位置にかかわらず**白紙削除の疑い**として結果一覧に報告するだけで、OCR は続けます(両面スキャンでは紙が 1 枚抜けると 2 ページ続けて欠けるため、1 ページだけの欠けはスキャナの白紙ページ自動削除で本の白紙ページが消えたものとみなします)。`--strict` を付けると、疑いも欠け扱い(`PGX_`)になります。次の限界があります。

- 最初のノンブルより前(前付け)と、最後のノンブルより後(奥付など)の欠けは検出できません
- ノンブルが漢数字・ローマ数字だけの本は、読み取れず「未検査」になります
- 小口(横の余白)に印字されたノンブルは読みません
- スキャナの白紙ページ自動削除が ON だと、本の白紙ページが消えて、1 ページだけの本物の落丁と区別できません。章扉の直前や、欠けの隣のページのノンブルが読めない場合も同じ扱い(白紙削除の疑い)です

書籍のスキャンでは、白紙ページの自動削除を OFF にすることをおすすめします。

### 再開と既存の Markdown の退避

- OCR の結果はページ単位でキャッシュされます。途中で止まっても、同じコマンドをもう一度実行すると続きから再開します(単体の `book2md` は入力のフォルダの `_book2md_work/<job_id>/`、遠隔の入口は Windows 側の `book2md\work` に置きます)
- 同じ名前の Markdown が既にあり、中身が今回の結果と違うときは、上書きする前に退避します。校正済みの Markdown を失わないためです。退避先は、単体の `book2md` では `_book2md_work/<job_id>/backup/`、`book2md-remote` では PDF のフォルダの `_book2md/backup/` で、名前は `<元の名前>.<日時>.md` です。中身が同じなら退避しません
- `book2md-remote` を Ctrl-C で止めると、終了コード 130 で終わります

### オプション

`book2md`(`inputs` は PDF またはフォルダで、複数指定できます)

| オプション | 内容 |
|---|---|
| `--work WORK` | 作業フォルダ(既定: 入力のフォルダ/`_book2md_work`) |
| `--out OUT` | Markdown の出力先(既定: PDF と同じフォルダ) |
| `--report REPORT` | 結果 JSON のパス |
| `--no-rename-missing` | 欠けのある PDF を `PGX_` にリネームしない |
| `--device {auto,gpu,cpu}` | 使うデバイス |
| `--model {auto,mobile,server}` | OCR モデル |
| `--on-uncertain {ocr,skip}` | ノンブルが読めず判定不能のときの扱い |
| `--strict` | 白紙削除の疑いも欠け扱いにする |
| `--fix` | 誤字辞書 `fix_ocr` を適用する(既定は適用しない) |
| `--keep-lines` | 行を段落にまとめず 1 行 1 段落で出す |
| `--include-pgx` | `PGX_` 始まりの PDF も処理する |
| `--check-only` | ページ欠けの検査だけ行う(OCR もリネームもしない) |

`book2md-remote`(`input` は PDF またはフォルダ)

| オプション | 内容 |
|---|---|
| `--host HOST` | ssh のホスト名(既定: `winpc`) |
| `--setup` | 遠隔の venv と PaddleOCR を導入する |
| `--dry-run` | 処理する/飛ばす一覧だけ出す(通信しない) |
| `--device {auto,gpu,cpu}` | 使うデバイス |
| `--model {auto,mobile,server}` | OCR モデル |
| `--on-uncertain {ocr,skip}` | ノンブルが読めず判定不能のときの扱い |
| `--strict` | 白紙削除の疑いも欠け扱いにする |
| `--fix` | 誤字辞書 `fix_ocr` を適用する(既定は適用しない) |
| `--keep-lines` | 行を段落にまとめず 1 行 1 段落で出す |
| `--include-pgx` | `PGX_` 始まりの PDF も処理する |
| `--check-only` | ページ欠けの検査だけ行う(OCR もリネームもしない) |

### 検証用: ページを抜いた PDF を作る

```bash
python scripts/drop_pages.py <in.pdf> <out.pdf> --drop 150,201,202
```

`--drop` は PDF のページ番号(1 始まり)です。欠けの検出を試すときに使います。
