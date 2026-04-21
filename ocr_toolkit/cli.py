"""ScanToXlsxStarter CLI: PDF→OCRテキスト までを一括実行する。

Usage:
    python -m ocr_toolkit.cli pdf2png input.pdf out/images/
    python -m ocr_toolkit.cli ocr out/images/ out/ocr/
    python -m ocr_toolkit.cli run config.yaml
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


def _cmd_pdf2png(args) -> int:
    from .pdf_tools import pdf_to_png
    pdf_to_png(
        args.pdf,
        args.out,
        first_page=args.first,
        last_page=args.last,
        dpi=args.dpi,
        prefix=args.prefix,
    )
    return 0


def _cmd_ocr(args) -> int:
    from .paddle_ocr import BatchOCR
    runner = BatchOCR(
        lang=args.lang,
        workers=args.workers,
        use_mobile=not args.server,
    )
    res = runner.run(
        args.src,
        args.out,
        glob_pattern=args.glob,
        skip_existing=not args.force,
    )
    print(res)
    return 0


def _cmd_progress(args) -> int:
    """toc.yaml + state.yaml から進捗テーブルを表示。"""
    from .progress import load_toc, load_state, render_status_table, summary_counts

    toc_path = Path(args.toc)
    state_path = Path(args.state) if args.state else toc_path.with_name("state.yaml")
    toc = load_toc(toc_path)
    state = load_state(state_path)

    print(f"# {toc.book}")
    print(f"toc:   {toc_path}")
    print(f"state: {state_path}{' (未生成)' if not state_path.exists() else ''}")
    print()
    print(render_status_table(toc, state))
    print()

    counts = summary_counts(toc, state)
    print("--- summary ---")
    for stage, c in counts.items():
        done = c.get("done", 0) + c.get("skipped", 0)
        total = sum(c.values())
        print(f"  {stage:10}  {done}/{total}  done={c.get('done',0)} skip={c.get('skipped',0)} "
              f"prog={c.get('in_progress',0)} pend={c.get('pending',0)} fail={c.get('failed',0)}")
    return 0


def _cmd_run(args) -> int:
    """config.yaml の手順に従って PDF→PNG→OCR を実行(簡易版)"""
    import yaml
    from .pdf_tools import pdf_to_png
    from .paddle_ocr import BatchOCR

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    base = Path(args.config).resolve().parent
    images = base / cfg.get("images_dir", "images")
    ocr_dir = base / cfg.get("ocr_dir", "ocr")

    pdf_cfg = cfg.get("pdf", {})
    if pdf_cfg.get("path"):
        pdf_to_png(
            pdf_cfg["path"],
            images,
            first_page=pdf_cfg.get("first_page", 1),
            last_page=pdf_cfg.get("last_page"),
            dpi=pdf_cfg.get("dpi", 300),
            prefix=pdf_cfg.get("prefix", "page"),
        )

    ocr_cfg = cfg.get("ocr", {})
    runner = BatchOCR(
        lang=ocr_cfg.get("lang", "japan"),
        workers=ocr_cfg.get("workers"),
        use_mobile=ocr_cfg.get("use_mobile", True),
    )
    runner.run(images, ocr_dir, glob_pattern=ocr_cfg.get("glob", "*.png"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ScanToXlsxStarter")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pdf2png", help="PDF→PNG変換(pdftoppm)")
    sp.add_argument("pdf")
    sp.add_argument("out")
    sp.add_argument("--first", type=int, default=1)
    sp.add_argument("--last", type=int, default=None)
    sp.add_argument("--dpi", type=int, default=300)
    sp.add_argument("--prefix", default="page")
    sp.set_defaults(func=_cmd_pdf2png)

    sp = sub.add_parser("ocr", help="画像ディレクトリを並列OCR")
    sp.add_argument("src")
    sp.add_argument("out")
    sp.add_argument("--lang", default="japan")
    sp.add_argument("--workers", type=int, default=None)
    sp.add_argument("--server", action="store_true",
                    help="mobileではなく server モデルを使用(高精度/低速)")
    sp.add_argument("--force", action="store_true", help="既存.txtも再OCR")
    sp.add_argument("--glob", default="*.png")
    sp.set_defaults(func=_cmd_ocr)

    sp = sub.add_parser("run", help="config.yamlでPDF→PNG→OCRを実行")
    sp.add_argument("config")
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("progress", help="toc.yaml/state.yaml から進捗を表示")
    sp.add_argument("toc", help="toc.yaml のパス")
    sp.add_argument("--state", help="state.yaml パス (デフォルト: toc.yaml と同じディレクトリ)")
    sp.set_defaults(func=_cmd_progress)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
