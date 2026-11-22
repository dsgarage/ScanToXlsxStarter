"""pages.py のテスト(Pillow / pypdfium2 が無い環境では skip)。合成 PDF のみ使う。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    import pypdfium2  # noqa: F401

    HAVE_LIBS = True
except ImportError:  # pragma: no cover
    HAVE_LIBS = False


def make_pdf(path: Path, n: int = 5, blank_pages: tuple[int, ...] = ()) -> None:
    imgs = []
    for i in range(1, n + 1):
        im = Image.new("RGB", (400, 600), "white")
        if i not in blank_pages:
            d = ImageDraw.Draw(im)
            d.rectangle([50, 100 + i * 10, 350, 400], fill="black")
        imgs.append(im)
    imgs[0].save(path, "PDF", save_all=True, append_images=imgs[1:])


@unittest.skipUnless(HAVE_LIBS, "Pillow / pypdfium2 が無い")
class PagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_raw(self):
        from ocr_toolkit.book2md.pages import extract_pages

        pdf = self.dir / "a.pdf"
        make_pdf(pdf, 5)
        info = extract_pages(pdf, self.dir / "pages")
        self.assertEqual(len(info), 5)
        self.assertTrue(all(e["method"] == "raw" for e in info))
        self.assertEqual(info[0]["file"], "p0001.jpg")
        self.assertEqual((info[0]["w"], info[0]["h"]), (400, 600))
        for e in info:
            self.assertGreater((self.dir / "pages" / e["file"]).stat().st_size, 0)

    def test_blank_detection(self):
        from ocr_toolkit.book2md.pages import extract_pages, page_stats

        pdf = self.dir / "b.pdf"
        make_pdf(pdf, 3, blank_pages=(2,))
        info = extract_pages(pdf, self.dir / "pages")
        flags = [page_stats(self.dir / "pages" / e["file"])["blank"] for e in info]
        self.assertEqual(flags, [False, True, False])

    def test_rerun_does_not_rebuild(self):
        from ocr_toolkit.book2md.pages import extract_pages

        pdf = self.dir / "c.pdf"
        make_pdf(pdf, 3)
        extract_pages(pdf, self.dir / "pages")
        files = sorted((self.dir / "pages").glob("p*.jpg"))
        old = [f.stat().st_mtime_ns for f in files]
        for f in files:
            os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        extract_pages(pdf, self.dir / "pages")
        self.assertTrue(all(f.stat().st_mtime_ns == 1_000_000_000 for f in files))
        self.assertEqual(len(old), 3)

    def test_margin_composite(self):
        from ocr_toolkit.book2md.pages import extract_pages, make_margin_composite

        pdf = self.dir / "d.pdf"
        make_pdf(pdf, 1)
        info = extract_pages(pdf, self.dir / "pages")
        out = self.dir / "m" / "p0001.png"
        r = make_margin_composite(self.dir / "pages" / info[0]["file"], out)
        self.assertEqual(r["top_h"], int(600 * 0.12))
        with Image.open(out) as im:
            self.assertEqual(im.size, (400, r["top_h"] * 2 + r["gap"]))
        mt = out.stat().st_mtime_ns
        make_margin_composite(self.dir / "pages" / info[0]["file"], out)
        self.assertEqual(out.stat().st_mtime_ns, mt)


if __name__ == "__main__":
    unittest.main()
