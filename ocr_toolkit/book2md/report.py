"""book2md の結果一覧(JSON/テキスト)を作る純粋関数(標準ライブラリのみ)"""
from __future__ import annotations

STATUS_LABELS = {
    "ok": "OK",
    "ok_unchecked": "OK(未検査)",
    "missing": "欠けあり",
    "uncertain_skipped": "判定不能",
    "checked_ok": "検査OK",
    "checked_uncertain": "検査不能",
    "failed": "失敗",
    "skipped_done": "済み",
    "skipped_pgx": "PGX済",
}


def build_report(books: list[dict], *, started: str, finished: str) -> dict:
    counts: dict[str, int] = {}
    for b in books:
        s = b.get("status")
        counts[s] = counts.get(s, 0) + 1
    return {
        "version": 1,
        "started": started,
        "finished": finished,
        "books": books,
        "counts": counts,
    }


def _gap_text(gap: dict) -> str:
    exact = gap.get("exact")
    if exact:
        return "印字 " + ",".join(str(v) for v in exact)
    a, b = gap.get("printed_from"), gap.get("printed_to")
    if a == b:
        return f"印字 {a}"
    return f"印字 {a}〜{b} のうち {gap.get('count')}"


def _memo(book: dict) -> str:
    status = book.get("status")
    check = book.get("check") or {}
    if status == "failed":
        return (book.get("error") or "")[:120]
    anchored_txt = ""
    if check.get("anchored") is not None and check.get("total_pages") is not None:
        anchored_txt = f"ノンブル確認 {check['anchored']}/{check['total_pages']}p"
    if status == "missing":
        gaps = check.get("missing") or []
        memo = "欠け: " + " / ".join(_gap_text(g) for g in gaps) if gaps else "欠け"
        sus = check.get("suspect_blank_removed") or []
        if sus:
            memo += " / 白紙削除疑い: " + " / ".join(_gap_text(g) for g in sus)
        if anchored_txt:
            memo += " / " + anchored_txt
        return memo
    if status in ("ok", "ok_unchecked", "uncertain_skipped", "checked_ok", "checked_uncertain"):
        parts: list[str] = []
        sus = check.get("suspect_blank_removed") or []
        if sus:
            parts.append("白紙削除疑い: " + " / ".join(_gap_text(g) for g in sus))
        for label, key in (
            ("重複", "duplicates"),
            ("入れ替わり疑い", "order_suspects"),
            ("白紙", "blank_pages"),
        ):
            src = book if key == "blank_pages" and book.get("blank_pages") else check
            n = len(src.get(key) or [])
            if n:
                parts.append(f"{label} {n}")
        fm = check.get("front_matter")
        if fm:
            parts.append(f"前付け PDF {fm[0]}〜{fm[1]}")
        if anchored_txt:
            parts.append(anchored_txt)
        return " / ".join(parts)
    return ""


def render_text(report: dict) -> str:
    books = report.get("books") or []
    counts = report.get("counts") or {}
    count_line = " / ".join(
        f"{STATUS_LABELS.get(s, s)} {c}" for s, c in counts.items()
    )
    lines = [f"book2md 結果 {report.get('finished')}", f"{len(books)} 冊: {count_line}"]
    for b in books:
        label = STATUS_LABELS.get(b.get("status"), str(b.get("status")))
        pages = b.get("pages")
        pages_txt = f"{pages}p" if pages is not None else "-"
        memo = _memo(b)
        line = f"[{label}] {b.get('name')} ({pages_txt})"
        if memo:
            line += "  " + memo
        lines.append(line)
    return "\n".join(lines) + "\n"
