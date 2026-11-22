"""本ごとの段の実行・再開・ロック・リネーム・レポート"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .common import (
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_OK_UNCHECKED,
    STATUS_SKIPPED_PGX,
    STATUS_UNCERTAIN_SKIPPED,
    PGX_PREFIX,
    atomic_write_json,
    atomic_write_text,
    job_id_for,
    pgx_name,
    read_json,
)
from .layout import collect_running_heads, page_orientation, page_to_text, to_boxes
from .markdown import PageEntry, build_markdown
from .nombre import PageObs, analyze, extract_numbers
from .pages import extract_pages, make_margin_composite, page_stats
from .report import build_report, render_text


@dataclass
class Options:
    work: Path
    out: Path | None = None
    rename_missing: bool = True
    device: str = "auto"
    model: str = "auto"
    on_uncertain: str = "ocr"  # "ocr" | "skip"
    strict: bool = False
    apply_fix: bool = False
    keep_lines: bool = False
    include_pgx: bool = False
    report: Path | None = None


class Engines:
    """OCR エンジンの遅延生成。テストでは margin / full を持つ偽物を渡す。"""

    def __init__(self, device_opt: str = "auto", model_opt: str = "auto"):
        self.device_opt = device_opt
        self.model_opt = model_opt
        self._device: str | None = None
        self._margin = None
        self._full = None

    def _dev(self) -> str:
        if self._device is None:
            from .engine import detect_device

            self._device = detect_device(self.device_opt)
        return self._device

    @property
    def margin(self):
        if self._margin is None:
            from .engine import OcrEngine

            self._margin = OcrEngine(model="mobile", device=self._dev(), textline_orientation=False)
        return self._margin

    @property
    def full(self):
        if self._full is None:
            from .engine import OcrEngine, resolve_model

            dev = self._dev()
            self._full = OcrEngine(
                model=resolve_model(self.model_opt, dev),
                device=dev,
                textline_orientation=True,
            )
        return self._full


def _log(msg: str) -> None:
    print(f"[book2md] {msg}", flush=True)


def list_inputs(inputs: list[str], include_pgx: bool) -> tuple[list[Path], list[Path]]:
    """(対象, 飛ばした PGX)。フォルダは直下の *.pdf(大文字小文字を区別しない、名前順)。"""
    found: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            found.extend(
                sorted(
                    (c for c in p.iterdir() if c.is_file() and c.suffix.lower() == ".pdf"),
                    key=lambda c: c.name,
                )
            )
        else:
            found.append(p)
    targets: list[Path] = []
    skipped: list[Path] = []
    for p in found:
        if p.name.startswith(PGX_PREFIX) and not include_pgx:
            skipped.append(p)
        else:
            targets.append(p)
    return targets, skipped


@contextlib.contextmanager
def acquire_lock(work_root: Path):
    """work/.lock を排他ロックする。取れなければ RuntimeError。"""
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    path = work_root / ".lock"
    f = open(path, "a+b")
    try:
        try:
            try:
                import msvcrt  # Windows

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                unlock = lambda: (f.seek(0), msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1))  # noqa: E731
            except ImportError:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                unlock = lambda: fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # noqa: E731
        except OSError:
            raise RuntimeError(f"別の book2md が実行中です: {path}") from None
        try:
            yield path
        finally:
            try:
                unlock()
            except Exception:
                pass
    finally:
        f.close()


def _display_name(pdf: Path) -> str:
    side = read_json(pdf.with_suffix(".json"), None)
    if isinstance(side, dict) and side.get("name"):
        return str(side["name"])
    return pdf.name


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def process_book(pdf: Path, opts: Options, engines) -> dict:
    pdf = Path(pdf)
    book: dict = {
        "job_id": None,
        "name": pdf.name,
        "source": str(pdf),
        "pages": None,
        "status": STATUS_FAILED,
        "md": None,
        "renamed_to": None,
        "error": None,
        "check": None,
        "ocr": None,
        "elapsed_sec": {},
    }
    try:
        return _process_book(pdf, opts, engines, book)
    except Exception as e:  # 1 冊の失敗で全体を止めない
        book["status"] = STATUS_FAILED
        book["error"] = f"{type(e).__name__}: {e}"
        _log(f"{book.get('job_id')} failed: {book['error']}")
        return book


def _process_book(pdf: Path, opts: Options, engines, book: dict) -> dict:
    job_id = job_id_for(pdf)
    wd = Path(opts.work) / job_id
    name = _display_name(pdf)
    book["job_id"] = job_id
    book["name"] = name
    _log(f"{job_id} = {name}")
    elapsed = book["elapsed_sec"]
    out_dir = Path(opts.out) if opts.out else pdf.parent

    # 2. 抽出
    t0 = time.time()
    pages_dir = wd / "pages"
    index_path = pages_dir / "index.json"
    index = read_json(index_path, None)
    if not (isinstance(index, list) and index and all(
        (pages_dir / e["file"]).exists() for e in index
    )):
        info = extract_pages(pdf, pages_dir)
        index = []
        for e in info:
            st = page_stats(pages_dir / e["file"])
            index.append({**e, **st})
        atomic_write_json(index_path, index)
    n = len(index)
    book["pages"] = n
    elapsed["extract"] = round(time.time() - t0, 2)

    # 3. 余白 OCR
    t0 = time.time()
    margin_dir = wd / "margin"
    for e in index:
        i = e["index"]
        mj = margin_dir / f"p{i:04d}.json"
        if mj.exists() and read_json(mj, None) is not None:
            continue
        png = margin_dir / f"p{i:04d}.png"
        make_margin_composite(pages_dir / e["file"], png)
        res = engines.margin.run(png)
        nums: list[int] = []
        for text, score in zip(res.get("texts", []), res.get("scores", [])):
            if score < 0.5:
                continue
            for v in extract_numbers(text, max_value=n + 200):
                if v not in nums:
                    nums.append(v)
        atomic_write_json(mj, {**res, "numbers": nums})
        if i % 50 == 0:
            _log(f"{job_id} margin {i}/{n}")
    elapsed["margin"] = round(time.time() - t0, 2)

    # 4. 検査
    obs = []
    for e in index:
        mj = read_json(margin_dir / f"p{e['index']:04d}.json", {}) or {}
        obs.append(PageObs(e["index"], list(mj.get("numbers", [])), bool(e.get("blank"))))
    check = analyze(obs, strict=opts.strict)
    check_dict = check.to_dict()
    atomic_write_json(wd / "check.json", check_dict)
    book["check"] = check_dict

    # 5. 分岐
    if check.status == "missing":
        book["status"] = STATUS_MISSING
        atomic_write_json(out_dir / f"{pdf.stem}.check.json", check_dict)
        if opts.rename_missing:
            dest = pdf.with_name(pgx_name(pdf.name))
            if dest.exists():
                book["status"] = STATUS_FAILED
                book["error"] = f"リネーム先が既にある: {dest}"
            else:
                pdf.rename(dest)
                book["renamed_to"] = str(dest)
        _log(f"{job_id} 欠けあり(OCR しません)")
        atomic_write_json(wd / "state.json", book)
        return book
    if check.status == "uncertain" and opts.on_uncertain == "skip":
        book["status"] = STATUS_UNCERTAIN_SKIPPED
        atomic_write_json(out_dir / f"{pdf.stem}.check.json", check_dict)
        atomic_write_json(wd / "state.json", book)
        return book

    # 6. 本文 OCR
    t0 = time.time()
    ocr_dir = wd / "ocr"
    todo = [e for e in index if read_json(ocr_dir / f"p{e['index']:04d}.json", None) is None]
    _log(f"{job_id} ocr new={len(todo)} cached={n - len(todo)}")
    for k, e in enumerate(todo, start=1):
        i = e["index"]
        oj = ocr_dir / f"p{i:04d}.json"
        if e.get("blank"):
            res = {"w": e["w"], "h": e["h"], "texts": [], "scores": [], "boxes": [], "blank": True}
        else:
            res = engines.full.run(pages_dir / e["file"])
        atomic_write_json(oj, res)
        if k % 20 == 0:
            rate = (time.time() - t0) / k
            _log(f"{job_id} ocr {k}/{len(todo)} 残り約 {int(rate * (len(todo) - k))} 秒")
    if any(not e.get("blank") for e in todo):
        # エンジンを使った回だけ情報を記録(キャッシュだけの再実行ではモデルを読み込まない)
        atomic_write_json(wd / "ocr_info.json", dict(engines.full.info))
    elapsed["ocr"] = round(time.time() - t0, 2)

    # 7. MD
    t0 = time.time()
    ocrs = [read_json(ocr_dir / f"p{e['index']:04d}.json", {}) for e in index]
    per_page = []
    for res in ocrs:
        boxes = to_boxes(res)
        per_page.append((boxes, float(res.get("h", 0)), page_orientation(boxes)))
    heads = collect_running_heads(per_page)
    entries = []
    for e, res in zip(index, ocrs):
        pt = page_to_text(res, heads, keep_lines=opts.keep_lines)
        entries.append(
            PageEntry(e["index"], check.printed_by_pdf.get(e["index"]), bool(e.get("blank")), pt.paragraphs)
        )
    full_info = read_json(wd / "ocr_info.json", {}) or {}
    unchecked = check.status == "uncertain"
    md = build_markdown(
        title=Path(name).stem,
        source_name=name,
        pages=entries,
        page_check="unchecked" if unchecked else "ok",
        missing_suspects=check.suspect_blank_removed,
        ocr_info=full_info,
        generated=_now(),
        apply_fix=opts.apply_fix,
    )
    md_path = out_dir / f"{pdf.stem}.md"
    atomic_write_text(md_path, md)
    atomic_write_json(out_dir / f"{pdf.stem}.check.json", check_dict)
    elapsed["md"] = round(time.time() - t0, 2)

    book["md"] = str(md_path)
    book["ocr"] = full_info or None
    book["status"] = STATUS_OK_UNCHECKED if unchecked else STATUS_OK
    atomic_write_json(wd / "state.json", book)
    return book


def run(inputs: list[str], opts: Options, engines=None) -> dict:
    started = _now()
    targets, skipped = list_inputs(inputs, opts.include_pgx)
    if engines is None:
        engines = Engines(opts.device, opts.model)
    books: list[dict] = []
    with acquire_lock(Path(opts.work)):
        for pdf in targets:
            books.append(process_book(pdf, opts, engines))
    for p in skipped:
        books.append(
            {
                "job_id": None,
                "name": p.name,
                "source": str(p),
                "pages": None,
                "status": STATUS_SKIPPED_PGX,
                "md": None,
                "renamed_to": None,
                "error": None,
                "check": None,
                "ocr": None,
                "elapsed_sec": {},
            }
        )
    report = build_report(books, started=started, finished=_now())
    if opts.report:
        rp = Path(opts.report)
    else:
        base = Path(opts.out) if opts.out else None
        if base is None:
            first = Path(inputs[0]) if inputs else Path(".")
            base = first if first.is_dir() else first.parent
        rp = base / "book2md_report.json"
    atomic_write_json(rp, report)
    print(render_text(report), end="", flush=True)
    return report
