import json
import unittest

from ocr_toolkit.book2md.markdown import PageEntry, build_markdown

INFO = {"model": "PP-OCRv5_server", "device": "gpu:0"}


def build(pages, **kw):
    args = dict(
        title="テスト本",
        source_name="テスト 本.pdf",
        pages=pages,
        page_check="ok",
        missing_suspects=[],
        ocr_info=INFO,
        generated="2026-11-22T18:00:00",
    )
    args.update(kw)
    return build_markdown(**args)


class MarkdownTest(unittest.TestCase):
    def pages(self):
        return [
            PageEntry(1, None, False, []),
            PageEntry(2, None, True, []),
            PageEntry(3, 1, False, ["テスト段落", "二つ目の段落"]),
        ]

    def test_front_matter_shape(self):
        md = build(self.pages())
        lines = md.split("\n")
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[1], 'title: "テスト本"')
        self.assertEqual(lines[2], 'source: "テスト 本.pdf"')
        self.assertEqual(lines[3], "pdf_pages: 3")
        self.assertEqual(lines[4], "page_check: ok")
        self.assertEqual(lines[5], "ocr_model: PP-OCRv5_server")
        self.assertEqual(lines[6], "ocr_device: gpu:0")
        self.assertEqual(lines[7], "generated: 2026-11-22T18:00:00")
        self.assertEqual(lines[8], "tool: ocr_toolkit book2md")
        self.assertEqual(lines[9], "---")
        self.assertNotIn("suspect_blank_removed", md)
        self.assertTrue(md.endswith("\n"))
        self.assertFalse(md.endswith("\n\n"))

    def test_title_json_escaped(self):
        md = build(self.pages(), title='a"b')
        self.assertIn('title: "a\\"b"', md)

    def test_markers_for_all_pages(self):
        md = build(self.pages())
        self.assertEqual(md.count("<!-- page:"), 3)
        self.assertIn("<!-- page: 1 printed: - -->", md)
        self.assertIn("<!-- page: 2 printed: - blank -->", md)
        self.assertIn("<!-- page: 3 printed: 1 -->\n\nテスト段落\n\n二つ目の段落\n", md)

    def test_suspect_line(self):
        md = build(self.pages(), missing_suspects=[{"printed_from": 22, "printed_to": 22, "count": 1}])
        line = [x for x in md.split("\n") if x.startswith("suspect_blank_removed:")][0]
        self.assertEqual(json.loads(line.split(": ", 1)[1]), [{"printed_from": 22, "printed_to": 22}])

    def test_unchecked(self):
        self.assertIn("page_check: unchecked", build(self.pages(), page_check="unchecked"))

    def test_comment_terminator_replaced(self):
        md = build([PageEntry(1, 1, False, ["前 --> 後"])])
        self.assertIn("前 -- > 後", md)
        self.assertEqual(md.count("-->"), 1)  # ページ目印の分だけ

    def test_empty_paragraph_dropped(self):
        md = build([PageEntry(1, 1, False, ["  ", "本文"])])
        self.assertIn("<!-- page: 1 printed: 1 -->\n\n本文\n", md)

    def test_fix_ocr_applied_only_when_asked(self):
        pages = [PageEntry(1, 1, False, ["キーワート"])]
        self.assertIn("キーワード", build(pages, apply_fix=True))
        self.assertNotIn("キーワード", build(pages))
        self.assertIn("キーワート", build(pages))


if __name__ == "__main__":
    unittest.main()
