# LLM 校正ワークフロー (OCR → 文脈校正 → 構造化データ)

PaddleOCR + `fix_ocr()` の辞書置換だけでは直らない **「文として成立しない」レベルの崩壊** を、Claude Opus の文脈推論で復元するための標準ワークフロー。

## いつ使うか

- OCR テキストに語順崩れ・欠字が多く、辞書置換では直らない
- 書籍単位で数百ページ / 数百日分の均質な崩壊データを一括処理したい
- 最終的に「日本語として成立するテキスト」をアプリや DB に投入したい

**fix_ocr で直るレベル** (文字列置換で直せるもの) はこのワークフローの対象外。まず `fix_ocr()` を通したうえで、残った崩壊を LLM で処理する。

## 前提

- Claude Code CLI が使える (Max プラン推奨 — 週次レート制限に注意)
- 校正辞書を Python モジュール (`dict`) として管理できる
- 並列サブエージェントを `model: "opus"` 指定で起動できる

## 全体フロー

```
  XLSX / JSON (OCR + fix_ocr 後)
    ↓  dump (ラベル付きテキストに抽出)
  dump.txt (人間可読のバッチ)
    ↓  Claude Opus サブエージェント × 並列 2
  llm_corrections_<batch>.py (CORRECTIONS dict)
    ↓  ocr_toolkit.corrections.load_merged()
  統合 CORRECTIONS
    ↓  ocr_toolkit.corrections.apply_corrections(callback=DB投入)
  本番 DB / 構造化出力
    ↓  ocr_toolkit.preview.write_comparison()
  比較 XLSX (目視レビュー)
```

## 手順

### 1. 崩壊テキストをバッチ単位でダンプ

XLSX / JSON / DB から校正対象を取り出し、1 バッチあたり **10〜50 項目** のテキストファイルに書き出す。

```python
# dump 例
for label, fields in source_rows:
    print(f"### {label}")
    for name, value in fields.items():
        print(f"--- {name} ---")
        print(value)
    print()
```

### 2. 並列 Opus サブエージェントで校正

Claude Code の `Agent` tool を `subagent_type: "general-purpose"` / `model: "opus"` で起動。

**同時並列は 2 本まで** が安定。3 本以上は API タイムアウトが増える (実測)。

#### プロンプト雛形

```
OCR 崩壊テキストを文脈校正して Python 辞書ファイルを作ります。

## タスク範囲
<例: 2月1日〜2月10日 (10日)>

## 入力
<ダンプファイルパス>

## 参考実装 (必読)
<既存の完成 CORRECTIONS ファイル>

## 校正ルール
1. 原文の意図と文体を最優先
2. 崩れた箇所 (文として成立しない部分) だけを最小限修正
3. 改行は元の位置を保持、OCR ノイズは削除
4. 意味を変えない・加筆しない
5. 修正不要な項目はキーを作らない (idempotent)

## 出力先
<書き出し先パス>

構造:
```python
CORRECTIONS: dict[tuple[int, int], dict[str, str]] = {}
CORRECTIONS[(2, 1)] = {"lead": "...", "leadText": "..."}
```

## 検証
```bash
python3 -c "import ...; print(len(mod.CORRECTIONS))"
```

成功したら「CORRECTIONS N 件作成」とだけ返してください。
**チャットに校正結果を書かず、ファイル書き込みのみ** (トークン節約/タイムアウト回避)。
```

#### タイムアウト回避のコツ

| 事象 | 対策 |
|---|---|
| `Stream idle timeout` | バッチサイズを下げる (50→30→10 日) |
| エージェント 3+ 並列で失敗 | 2 並列まで |
| 出力トークン膨張 | プロンプトで「校正結果はチャットに書かずファイルのみ」と明示 |
| 複数フィールド × 大量日数 | フィールド分離 or 日数分離 |

### 3. 統合・バリデーション

```python
from ocr_toolkit.corrections import load_merged, validate

files = [Path("corrections_batch1.py"), Path("corrections_batch2.py"), ...]
merged = load_merged(files)

validate(
    merged,
    allowed_fields={"lead", "leadText", "strengths", "weaknesses"},
    json_array_fields={"strengths", "weaknesses"},
)
```

### 4. DB / 出力先に適用

```python
from ocr_toolkit.corrections import apply_corrections

def apply_row(row_dict, patch):
    # 例: PostgreSQL UPDATE
    cols = ", ".join(f'"{k}" = %s' for k in patch)
    cur.execute(
        f'UPDATE mytable SET {cols} WHERE id = %s',
        list(patch.values()) + [row_dict["id"]],
    )

summary = apply_corrections(
    rows=source_rows,
    corrections=merged,
    key_fn=lambda r: (r["month"], r["day"]),
    apply_row=apply_row,
)
print(summary)  # {"total": 366, "matched": 350, "applied": 350}
```

### 5. 比較 XLSX でレビュー

```python
from ocr_toolkit.preview import write_comparison, default_warn_fn

write_comparison(
    output=Path("preview_corrected.xlsx"),
    rows=[
        {
            "label": f"{r['month']}/{r['day']}",
            "_before": r,                          # 元データ
            "_after": {**r, **merged.get((r["month"], r["day"]), {})},
        }
        for r in source_rows
    ],
    fields=("lead", "leadText"),
    emphasis_fields=("lead",),
    warn_fn=lambda r: default_warn_fn(r, fields=("lead", "leadText"),
                                       min_lengths={"leadText": 20}),
)
```

## 実績ベースの推奨値 (FortuneTelling 事例)

| 指標 | 値 | 備考 |
|---|---|---|
| バッチサイズ | 10〜50 項目 | 7 フィールド × 10日が最安定 |
| 並列数 | 2 | 3 以上は失敗率上昇 |
| 1 バッチあたり所要時間 | 5〜10 分 | Opus の stream 時間含む |
| トークン / バッチ | 60k〜90k | 合計 30〜70 バッチで書籍1冊完了 |
| 週次トークン消費 | 3〜5 MT | Max プランで 366日 × 7 フィールド書籍 1 冊 |

## アンチパターン

- ❌ プロンプトで「チャットにも校正結果を全文書け」と指示 → タイムアウト頻発
- ❌ バッチを 60 項目以上 → Stream idle timeout で中断、ファイル未生成
- ❌ 並列 4 本以上 → Opus クォータ競合 + タイムアウト
- ❌ 参考実装ファイルを渡さない → 文体が揺れる

## 関連ファイル

- `ocr_toolkit/corrections.py` — CORRECTIONS dict のロード・適用ヘルパ
- `ocr_toolkit/preview.py` — 比較 XLSX ジェネレーター
- `ocr_toolkit/fix_ocr.py` — 事前の文字列置換辞書
