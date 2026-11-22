import unittest

from ocr_toolkit.book2md.report import build_report, render_text


def _book(name, status, **kw):
    d = {"job_id": "abc", "name": name, "pages": 10, "status": status, "check": None, "error": None}
    d.update(kw)
    return d


class ReportTest(unittest.TestCase):
    def test_counts(self):
        books = [_book("a.pdf", "ok"), _book("b.pdf", "ok"), _book("c.pdf", "missing")]
        r = build_report(books, started="s", finished="f")
        self.assertEqual(r["counts"], {"ok": 2, "missing": 1})
        self.assertEqual(r["version"], 1)
        self.assertEqual(len(r["books"]), 3)

    def test_status_labels(self):
        statuses = ["ok", "ok_unchecked", "missing", "uncertain_skipped", "failed", "skipped_done", "skipped_pgx"]
        books = [_book(f"{s}.pdf", s) for s in statuses]
        text = render_text(build_report(books, started="s", finished="f"))
        for label in ["[OK]", "[OK(未検査)]", "[欠けあり]", "[判定不能]", "[失敗]", "[済み]", "[PGX済]"]:
            self.assertIn(label, text)
        self.assertTrue(text.startswith("book2md 結果 f"))

    def test_missing_exact(self):
        check = {"missing": [{"printed_from": 120, "printed_to": 121, "count": 2, "exact": [120, 121]}]}
        text = render_text(build_report([_book("a.pdf", "missing", check=check)], started="s", finished="f"))
        self.assertIn("欠け: 印字 120,121", text)

    def test_missing_range_without_exact(self):
        check = {"missing": [{"printed_from": 120, "printed_to": 121, "count": 1, "exact": None}]}
        text = render_text(build_report([_book("a.pdf", "missing", check=check)], started="s", finished="f"))
        self.assertIn("欠け: 印字 120〜121 のうち 1", text)

    def test_missing_single_and_multiple(self):
        check = {
            "missing": [
                {"printed_from": 22, "printed_to": 22, "count": 1, "exact": None},
                {"printed_from": 120, "printed_to": 121, "count": 1, "exact": None},
            ]
        }
        text = render_text(build_report([_book("a.pdf", "missing", check=check)], started="s", finished="f"))
        self.assertIn("欠け: 印字 22 / 印字 120〜121 のうち 1", text)

    def test_ok_memo_nonzero_only(self):
        check = {
            "suspect_blank_removed": [{"printed_from": 22, "printed_to": 22, "count": 1, "exact": None}],
            "duplicates": [],
            "order_suspects": [{}, {}],
            "blank_pages": [],
            "front_matter": [1, 4],
        }
        text = render_text(build_report([_book("a.pdf", "ok", check=check)], started="s", finished="f"))
        self.assertIn("白紙削除疑い: 印字 22 / 入れ替わり疑い 2 / 前付け PDF 1〜4", text)
        self.assertNotIn("重複", text)

    def test_suspect_blank_removed_with_numbers(self):
        check = {
            "suspect_blank_removed": [
                {"printed_from": 120, "printed_to": 120, "count": 1, "exact": [120]},
                {"printed_from": 200, "printed_to": 201, "count": 1, "exact": None},
            ]
        }
        text = render_text(build_report([_book("a.pdf", "ok", check=check)], started="s", finished="f"))
        self.assertIn("白紙削除疑い: 印字 120 / 印字 200〜201 のうち 1", text)

    def test_checked_labels(self):
        books = [_book("a.pdf", "checked_ok"), _book("b.pdf", "checked_uncertain")]
        text = render_text(build_report(books, started="s", finished="f"))
        self.assertIn("[検査OK]", text)
        self.assertIn("[検査不能]", text)

    def test_missing_memo_with_suspect_and_anchored(self):
        check = {
            "missing": [{"printed_from": 120, "printed_to": 121, "count": 2, "exact": [120, 121]}],
            "suspect_blank_removed": [{"printed_from": 22, "printed_to": 22, "count": 1, "exact": None}],
            "anchored": 25,
            "total_pages": 30,
        }
        text = render_text(build_report([_book("a.pdf", "missing", check=check)], started="s", finished="f"))
        self.assertIn("欠け: 印字 120,121 / 白紙削除疑い: 印字 22 / ノンブル確認 25/30p", text)

    def test_ok_memo_anchored(self):
        check = {"anchored": 8, "total_pages": 30, "blank_pages": [{}]}
        text = render_text(build_report([_book("a.pdf", "checked_ok", check=check)], started="s", finished="f"))
        self.assertIn("白紙 1 / ノンブル確認 8/30p", text)

    def test_ok_memo_prefers_book_blank_pages(self):
        check = {"anchored": 8, "total_pages": 30, "blank_pages": []}
        b = _book("a.pdf", "ok", check=check, blank_pages=[4, 9])
        text = render_text(build_report([b], started="s", finished="f"))
        self.assertIn("白紙 2 / ノンブル確認 8/30p", text)

    def test_unread_lines_shown_first(self):
        check = {"anchored": 8, "total_pages": 30}
        b = _book("a.pdf", "ok", check=check, unread_lines=7, unread_pages=[3, 5])
        text = render_text(build_report([b], started="s", finished="f"))
        self.assertIn("読めなかった行 7(2 ページ) / ノンブル確認 8/30p", text)
        self.assertLess(text.index("読めなかった行"), text.index("ノンブル確認"))

    def test_unread_lines_zero_or_missing_not_shown(self):
        books = [
            _book("a.pdf", "ok", unread_lines=0, unread_pages=[]),
            _book("b.pdf", "ok"),
        ]
        text = render_text(build_report(books, started="s", finished="f"))
        self.assertNotIn("読めなかった行", text)

    def test_failed_error_truncated(self):
        text = render_text(build_report([_book("a.pdf", "failed", error="E" * 300)], started="s", finished="f"))
        self.assertIn("E" * 120, text)
        self.assertNotIn("E" * 121, text)


if __name__ == "__main__":
    unittest.main()
