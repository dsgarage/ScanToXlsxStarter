"""runner.py のテスト。合成 PDF と偽エンジンだけを使い、実際の OCR は走らせない。"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    import pypdfium2  # noqa: F401

    HAVE_LIBS = True
except ImportError:  # pragma: no cover
    HAVE_LIBS = False


def make_pdf(path: Path, n: int) -> None:
    imgs = []
    for i in range(1, n + 1):
        im = Image.new("RGB", (400, 600), "white")
        ImageDraw.Draw(im).rectangle([50, 100 + i * 5, 350, 400], fill="black")
        imgs.append(im)
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:])


def _page_no(path) -> int:
    return int(re.search(r"p(\d{4})", Path(path).name).group(1))


class FakeMargin:
    """余白画像のファイル名から PDF ページ番号を取り、印字ノンブルを返す。"""

    def __init__(self, printed: dict[int, int]):
        self.printed = printed
        self.calls = 0
        self.info = {"model": "fake_mobile", "device": "cpu"}

    def run(self, image_path):
        self.calls += 1
        v = self.printed.get(_page_no(image_path))
        texts = [str(v)] if v is not None else []
        return {
            "w": 400,
            "h": 264,
            "texts": texts,
            "scores": [0.99] * len(texts),
            "boxes": [[150, 200, 200, 240]] * len(texts),
        }


class FakeFull:
    def __init__(self):
        self.calls = 0
        self.info = {"model": "fake_full", "device": "cpu"}

    def run(self, image_path):
        self.calls += 1
        n = _page_no(image_path)
        return {
            "w": 400,
            "h": 600,
            "texts": [f"ダミー本文{n}"],
            "scores": [0.99],
            "boxes": [[180, 150, 220, 450]],
        }


class FakeEngines:
    def __init__(self, printed: dict[int, int]):
        self.margin = FakeMargin(printed)
        self.full = FakeFull()


# 30 ページ: PDF 1〜2 は前付け(無番号)、PDF 3 から印字 1 から
OK_PRINTED = {i: i - 2 for i in range(3, 31)}
# 29 ページ: 前後のページも読めている本文の途中(印字 13)が 1 ページ抜けた筋書き
MISSING_PRINTED = {**{i: i - 2 for i in range(3, 15)}, **{i: i - 1 for i in range(15, 30)}}


@unittest.skipUnless(HAVE_LIBS, "Pillow / pypdfium2 が無い")
class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def opts(self, **kw):
        from ocr_toolkit.book2md.runner import Options

        return Options(work=self.dir / "work", report=self.dir / "report.json", **kw)

    def test_ok_then_rerun_uses_cache(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "本 a.pdf"
        make_pdf(pdf, 30)
        eng = FakeEngines(OK_PRINTED)
        rep = run([str(self.dir)], self.opts(), eng)
        self.assertEqual(rep["books"][0]["status"], "ok")
        md = (self.dir / "本 a.md").read_text(encoding="utf-8")
        self.assertEqual(md.count("<!-- page:"), 30)
        self.assertIn("<!-- page: 3 printed: 1 -->", md)
        self.assertGreater(eng.margin.calls, 0)
        self.assertGreater(eng.full.calls, 0)

        eng2 = FakeEngines(OK_PRINTED)
        rep2 = run([str(self.dir)], self.opts(), eng2)
        self.assertEqual(rep2["books"][0]["status"], "ok")
        self.assertEqual(eng2.margin.calls, 0)
        self.assertEqual(eng2.full.calls, 0)

    def test_missing_renames_and_skips_ocr(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "欠け 本.pdf"
        make_pdf(pdf, 29)
        eng = FakeEngines(MISSING_PRINTED)
        rep = run([str(pdf)], self.opts(), eng)
        book = rep["books"][0]
        self.assertEqual(book["status"], "missing")
        self.assertFalse(pdf.exists())
        self.assertTrue((self.dir / "PGX_欠け 本.pdf").exists())
        self.assertEqual(book["check"]["missing"][0]["exact"], [13])
        self.assertEqual(eng.full.calls, 0)
        self.assertFalse(list((self.dir / "work").glob("*/ocr")))
        self.assertFalse((self.dir / "欠け 本.md").exists())

    def test_pgx_input_is_skipped(self):
        from ocr_toolkit.book2md.runner import list_inputs

        (self.dir / "PGX_x.pdf").write_bytes(b"")
        (self.dir / "b.PDF").write_bytes(b"")
        targets, skipped = list_inputs([str(self.dir)], include_pgx=False)
        self.assertEqual([p.name for p in targets], ["b.PDF"])
        self.assertEqual([p.name for p in skipped], ["PGX_x.pdf"])

    def test_lock_double_acquire(self):
        from ocr_toolkit.book2md.runner import acquire_lock

        with acquire_lock(self.dir / "w"):
            with self.assertRaises(RuntimeError):
                with acquire_lock(self.dir / "w"):
                    pass
        with acquire_lock(self.dir / "w"):  # 解放後は取れる
            pass


if __name__ == "__main__":
    unittest.main()
