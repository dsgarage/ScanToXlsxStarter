"""目次 (TOC) ベースの進捗管理モジュール。

書籍 OCR → XLSX → LLM 校正 → DB 投入 の各ステージを、
章 (section) 単位で追跡する。任意ステージから再開可能。

## ファイル構成

書籍ディレクトリに 2 つの YAML を置く:

```
<book>/
├── toc.yaml      # 目次定義 (人間が一度書く)
└── state.yaml    # 進捗状態 (パイプラインが自動更新)
```

### toc.yaml スキーマ

```yaml
book: 誕生日辞典 (ゲイリー・ゴールドシュナイダー)
sections:
  - id: ch01_aries
    title: 牡羊座
    pages: [29, 90]              # PDF ページ範囲 (両端含む)
    days: ["3-21", "3-22", ..., "4-19"]   # 任意: 章に含まれる日
  - id: ch02_taurus
    title: 牡牛座
    pages: [91, 152]
    days: ["4-20", ..., "5-20"]
```

### state.yaml スキーマ

```yaml
sections:
  ch01_aries:
    ocr:       {status: done, at: 2026-04-21T10:00:00, pages: 62}
    detect:    {status: done, at: 2026-04-21T10:01:00, suspicious: 8, clean: 54}
    llm:       {status: in_progress, at: 2026-04-21T10:30:00, batches: [batch1.py], applied: 8}
    db:        {status: pending}
    xlsx_sync: {status: pending}
  ch02_taurus:
    ...
```

## トークンコスト

各ステージのコストを `STAGE_COSTS` で明示:
- ocr / detect / db / xlsx_sync: ローカル処理、Claude トークン消費なし
- llm: Claude Opus 経由、suspicion フィルタ通過分のみ課金
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise ImportError("progress.py は PyYAML に依存します。`pip install pyyaml`") from e


# ============================================================================
# ステージ定義
# ============================================================================
Stage = Literal["ocr", "detect", "llm", "db", "xlsx_sync"]
Status = Literal["pending", "in_progress", "done", "skipped", "failed"]

ALL_STAGES: tuple[Stage, ...] = ("ocr", "detect", "llm", "db", "xlsx_sync")

# トークンコスト判定 (True = Claude 課金あり)
STAGE_COSTS: dict[Stage, bool] = {
    "ocr": False,        # PaddleOCR ローカル
    "detect": False,     # suspicion 計算のみ
    "llm": True,         # Claude Opus 課金 ★
    "db": False,         # PostgreSQL I/O
    "xlsx_sync": False,  # openpyxl 書き込み
}


# ============================================================================
# データクラス
# ============================================================================
@dataclass
class Section:
    """目次の 1 章。"""
    id: str
    title: str
    pages: tuple[int, int]               # (first, last) inclusive
    days: list[str] = field(default_factory=list)  # "M-D" 形式 (任意)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TOC:
    """書籍全体の目次。"""
    book: str
    sections: list[Section] = field(default_factory=list)

    def section(self, sid: str) -> Section:
        for s in self.sections:
            if s.id == sid:
                return s
        raise KeyError(f"section not found: {sid}")

    def section_ids(self) -> list[str]:
        return [s.id for s in self.sections]


@dataclass
class StageState:
    """1 ステージの状態。"""
    status: Status = "pending"
    at: str | None = None                # ISO 8601
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SectionState:
    """1 章の全ステージ状態。"""
    stages: dict[Stage, StageState] = field(default_factory=lambda: {s: StageState() for s in ALL_STAGES})


@dataclass
class State:
    """書籍全体の進捗状態。"""
    sections: dict[str, SectionState] = field(default_factory=dict)


# ============================================================================
# YAML I/O
# ============================================================================
def load_toc(path: Path) -> TOC:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    book = data.get("book", "")
    sections = []
    for s in data.get("sections", []):
        pages = s["pages"]
        sections.append(Section(
            id=s["id"],
            title=s.get("title", s["id"]),
            pages=(int(pages[0]), int(pages[1])),
            days=list(s.get("days", [])),
            extra={k: v for k, v in s.items() if k not in {"id", "title", "pages", "days"}},
        ))
    return TOC(book=book, sections=sections)


def load_state(path: Path) -> State:
    p = Path(path)
    if not p.exists():
        return State()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    state = State()
    for sid, sdata in (data.get("sections") or {}).items():
        ss = SectionState()
        for stage in ALL_STAGES:
            entry = (sdata or {}).get(stage) or {}
            ss.stages[stage] = StageState(
                status=entry.get("status", "pending"),
                at=entry.get("at"),
                notes={k: v for k, v in entry.items() if k not in {"status", "at"}},
            )
        state.sections[sid] = ss
    return state


def save_state(path: Path, state: State) -> None:
    out = {"sections": {}}
    for sid, ss in state.sections.items():
        sec_out = {}
        for stage, st in ss.stages.items():
            entry = {"status": st.status}
            if st.at:
                entry["at"] = st.at
            entry.update(st.notes)
            sec_out[stage] = entry
        out["sections"][sid] = sec_out
    Path(path).write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ============================================================================
# ステージ遷移 API
# ============================================================================
def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def mark(
    state: State,
    section_id: str,
    stage: Stage,
    status: Status,
    **notes: Any,
) -> None:
    """指定セクション × ステージの状態を更新する (in-place)。"""
    if section_id not in state.sections:
        state.sections[section_id] = SectionState()
    ss = state.sections[section_id]
    ss.stages[stage] = StageState(status=status, at=now_iso(), notes=dict(notes))


def get(state: State, section_id: str, stage: Stage) -> StageState:
    if section_id not in state.sections:
        return StageState()
    return state.sections[section_id].stages.get(stage, StageState())


def is_done(state: State, section_id: str, stage: Stage) -> bool:
    return get(state, section_id, stage).status in {"done", "skipped"}


def pending_sections(state: State, toc: TOC, stage: Stage) -> list[str]:
    """指定ステージが未完了 (pending/in_progress/failed) のセクション ID 一覧。"""
    out = []
    for sid in toc.section_ids():
        st = get(state, sid, stage)
        if st.status not in {"done", "skipped"}:
            out.append(sid)
    return out


# ============================================================================
# 進捗テーブル表示
# ============================================================================
STATUS_GLYPH: dict[Status, str] = {
    "pending": "·",
    "in_progress": "▶",
    "done": "✓",
    "skipped": "—",
    "failed": "✗",
}


def render_status_table(toc: TOC, state: State, *, show_token_cost: bool = True) -> str:
    """進捗テーブルを Markdown 風文字列で返す。"""
    headers = ["section", "title"] + list(ALL_STAGES)
    rows = [headers]
    for sec in toc.sections:
        row = [sec.id, sec.title]
        for stage in ALL_STAGES:
            st = get(state, sec.id, stage)
            row.append(STATUS_GLYPH.get(st.status, "?"))
        rows.append(row)

    widths = [max(len(str(r[i])) for r in rows) for i in range(len(headers))]
    lines = []
    for i, r in enumerate(rows):
        line = "  ".join(str(c).ljust(widths[j]) for j, c in enumerate(r))
        lines.append(line)
        if i == 0:
            lines.append("  ".join("-" * w for w in widths))

    if show_token_cost:
        lines.append("")
        lines.append("legend: " + "  ".join(f"{g}={s}" for s, g in STATUS_GLYPH.items()))
        cost_line = "stages: " + "  ".join(
            f"{stage}{'(★token)' if STAGE_COSTS[stage] else ''}" for stage in ALL_STAGES
        )
        lines.append(cost_line)

    return "\n".join(lines)


def summary_counts(toc: TOC, state: State) -> dict[Stage, dict[Status, int]]:
    """各ステージの状態別カウントを返す。"""
    out: dict[Stage, dict[Status, int]] = {
        stage: {s: 0 for s in STATUS_GLYPH} for stage in ALL_STAGES
    }
    for sec in toc.sections:
        for stage in ALL_STAGES:
            st = get(state, sec.id, stage)
            out[stage][st.status] += 1
    return out
