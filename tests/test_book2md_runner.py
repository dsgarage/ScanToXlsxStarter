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
# 28 ページ: 前後のページも読めている本文の途中(印字 13、14)が連続 2 ページ抜けた筋書き
MISSING_PRINTED = {**{i: i - 2 for i in range(3, 15)}, **{i: i for i in range(15, 29)}}
# 30 ページ: 印字 5〜9 の 5 ページが 2 回出る二重スキャンの筋書き(PDF 12〜16 が PDF 7〜11 の重複)
DUP_PRINTED = {**{i: i - 2 for i in range(3, 12)}, **{i: i - 7 for i in range(12, 31)}}


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

    def test_existing_md_is_backed_up_only_when_changed(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "本 a.pdf"
        make_pdf(pdf, 30)
        rep = run([str(self.dir)], self.opts(), FakeEngines(OK_PRINTED))
        job_id = rep["books"][0]["job_id"]
        md_path = self.dir / "本 a.md"
        original = md_path.read_text(encoding="utf-8")
        backup = self.dir / "work" / job_id / "backup"

        # 書き換えずに再実行 → 退避なし
        run([str(self.dir)], self.opts(), FakeEngines(OK_PRINTED))
        self.assertFalse(backup.exists() and any(backup.iterdir()))

        # 書き換えて再実行 → OCR の内容に戻り、書き換えた内容が退避される
        md_path.write_text("校正済みのダミー", encoding="utf-8")
        run([str(self.dir)], self.opts(), FakeEngines(OK_PRINTED))
        self.assertEqual(md_path.read_text(encoding="utf-8"), original)
        files = list(backup.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(encoding="utf-8"), "校正済みのダミー")

    def test_missing_renames_and_skips_ocr(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "欠け 本.pdf"
        make_pdf(pdf, 28)
        eng = FakeEngines(MISSING_PRINTED)
        rep = run([str(pdf)], self.opts(), eng)
        book = rep["books"][0]
        self.assertEqual(book["status"], "missing")
        self.assertFalse(pdf.exists())
        self.assertTrue((self.dir / "PGX_欠け 本.pdf").exists())
        self.assertEqual(book["check"]["missing"][0]["exact"], [13, 14])
        self.assertEqual(book["check"]["missing"][0]["count"], 2)
        self.assertEqual(eng.full.calls, 0)
        self.assertFalse(list((self.dir / "work").glob("*/ocr")))
        self.assertFalse((self.dir / "欠け 本.md").exists())

    def test_check_only_ok_then_full_run_uses_margin_cache(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "本 c.pdf"
        make_pdf(pdf, 30)
        eng = FakeEngines(OK_PRINTED)
        rep = run([str(pdf)], self.opts(check_only=True), eng)
        book = rep["books"][0]
        self.assertEqual(book["status"], "checked_ok")
        self.assertFalse((self.dir / "本 c.md").exists())
        self.assertFalse(list((self.dir / "work").glob("*/ocr")))
        self.assertEqual(eng.full.calls, 0)
        self.assertGreater(eng.margin.calls, 0)
        self.assertTrue((self.dir / "本 c.check.json").exists())
        self.assertTrue(pdf.exists())

        eng2 = FakeEngines(OK_PRINTED)
        rep2 = run([str(pdf)], self.opts(check_only=False), eng2)
        self.assertEqual(rep2["books"][0]["status"], "ok")
        self.assertEqual(eng2.margin.calls, 0)
        self.assertGreater(eng2.full.calls, 0)
        self.assertTrue((self.dir / "本 c.md").exists())

    def test_check_only_missing_does_not_rename(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "欠け 本.pdf"
        make_pdf(pdf, 28)
        eng = FakeEngines(MISSING_PRINTED)
        rep = run([str(pdf)], self.opts(check_only=True, rename_missing=True), eng)
        self.assertEqual(rep["books"][0]["status"], "missing")
        self.assertTrue(pdf.exists())
        self.assertFalse((self.dir / "PGX_欠け 本.pdf").exists())
        self.assertEqual(eng.full.calls, 0)
        self.assertFalse(list((self.dir / "work").glob("*/ocr")))
        self.assertFalse((self.dir / "欠け 本.md").exists())

    def test_one_page_gap_is_suspect_and_ocr_continues(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "疑い 本.pdf"
        make_pdf(pdf, 29)
        one_gap = {**{i: i - 2 for i in range(3, 15)}, **{i: i - 1 for i in range(15, 30)}}
        eng = FakeEngines(one_gap)
        rep = run([str(pdf)], self.opts(), eng)
        self.assertEqual(rep["books"][0]["status"], "ok")
        self.assertEqual(len(rep["books"][0]["check"]["suspect_blank_removed"]), 1)
        self.assertTrue(pdf.exists())
        self.assertGreater(eng.full.calls, 0)

    def test_stale_blank_in_index_is_ignored(self):
        from ocr_toolkit.book2md.common import atomic_write_json, read_json
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "本 d.pdf"
        make_pdf(pdf, 30)
        eng = FakeEngines(OK_PRINTED)
        rep = run([str(pdf)], self.opts(), eng)
        self.assertEqual(eng.full.calls, 30)
        wd = self.dir / "work" / rep["books"][0]["job_id"]
        idx = read_json(wd / "pages" / "index.json", None)
        for e in idx:
            e["blank"] = True
        atomic_write_json(wd / "pages" / "index.json", idx)
        (wd / "ocr").rename(wd / "ocr_old")

        eng2 = FakeEngines(OK_PRINTED)
        rep2 = run([str(pdf)], self.opts(), eng2)
        self.assertEqual(rep2["books"][0]["status"], "ok")
        self.assertEqual(eng2.full.calls, 30)
        self.assertEqual(rep2["books"][0]["blank_pages"], [])
        self.assertTrue((wd / "ocr_info.json").exists())

    def test_blank_is_decided_by_ocr_result(self):
        from ocr_toolkit.book2md.runner import run

        class EmptyFull(FakeFull):
            def run(self, image_path):
                res = super().run(image_path)
                if _page_no(image_path) == 5:
                    res.update(texts=[], scores=[], boxes=[])
                return res

        pdf = self.dir / "本 e.pdf"
        make_pdf(pdf, 30)
        eng = FakeEngines(OK_PRINTED)
        eng.full = EmptyFull()
        rep = run([str(pdf)], self.opts(), eng)
        self.assertEqual(rep["books"][0]["blank_pages"], [5])
        md = (self.dir / "本 e.md").read_text(encoding="utf-8")
        self.assertIn("<!-- page: 5 printed: 3 blank -->", md)
        self.assertEqual(md.count(" blank -->"), 1)

    def test_duplicate_scan_is_marked_and_body_kept(self):
        from ocr_toolkit.book2md.runner import run

        pdf = self.dir / "本 f.pdf"
        make_pdf(pdf, 30)
        eng = FakeEngines(DUP_PRINTED)
        rep = run([str(pdf)], self.opts(), eng)
        self.assertEqual(rep["books"][0]["status"], "ok")
        md = (self.dir / "本 f.md").read_text(encoding="utf-8")
        self.assertIn("duplicate_pages: 5", md)
        self.assertIn("<!-- page: 7 printed: 5 dup-of: 12 -->", md)
        self.assertIn("<!-- page: 12 printed: 5 -->", md)
        self.assertEqual(md.count(" dup-of: "), 5)
        self.assertIn("ダミー本文7", md)
        self.assertIn("ダミー本文12", md)

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
