import unittest

from ocr_toolkit.book2md.nombre import PageObs, analyze, extract_numbers


def make(n, printed, blank=()):
    """PDF ページ 1..n の PageObs を作る。printed = {pdf番号: [候補, ...]}"""
    return [PageObs(i, list(printed.get(i, [])), i in blank) for i in range(1, n + 1)]


def book(front=4, total=300, skip=(), extra=None):
    """前付け front ページ + 本文。本文は印字 1.. を連番で付ける(skip の印字番号は欠けとして詰める)"""
    printed = {}
    p = 1
    pdf = front + 1
    while pdf <= total:
        if p in skip:
            p += 1
            continue
        printed[pdf] = [p]
        p += 1
        pdf += 1
    return printed


class ExtractNumbersTest(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(extract_numbers("275 | 第8章 物事を…"), [275])
        self.assertEqual(extract_numbers("１２３"), [123])
        self.assertEqual(extract_numbers("2 75"), [275])
        self.assertEqual(extract_numbers("第3章"), [])
        self.assertEqual(extract_numbers("3.2 節"), [])

    def test_range_and_dedupe(self):
        self.assertEqual(extract_numbers("0 5 5"), [55])
        self.assertEqual(extract_numbers("10 | 20 | 10"), [10, 20])
        self.assertEqual(extract_numbers("12345"), [])
        self.assertEqual(extract_numbers("500", max_value=300), [])


class AnalyzeTest(unittest.TestCase):
    def test_complete_book(self):
        r = analyze(make(300, book()))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.front_matter, [1, 4])
        self.assertEqual(r.gating, [])
        self.assertEqual(r.printed_by_pdf[5], 1)

    def test_one_missing_is_suspect_blank_removed(self):
        # 前後とも番号が読めている 1 ページ欠けは、白紙削除の疑い(既定は ok)
        r = analyze(make(299, book(total=299, skip={120})))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.gating, [])
        self.assertEqual(r.missing, [])
        self.assertEqual(len(r.suspect_blank_removed), 1)
        self.assertEqual(r.suspect_blank_removed[0]["count"], 1)
        self.assertEqual(r.suspect_blank_removed[0]["exact"], [120])
        r2 = analyze(make(299, book(total=299, skip={120})), strict=True)
        self.assertEqual(r2.status, "missing")
        self.assertEqual(r2.gating, ["suspect_blank_removed"])

    def test_two_separate_one_page_gaps(self):
        r = analyze(make(298, book(total=298, skip={100, 200})))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.missing, [])
        self.assertEqual(len(r.suspect_blank_removed), 2)

    def test_two_missing(self):
        r = analyze(make(298, book(total=298, skip={120, 121})))
        self.assertEqual(r.status, "missing")
        self.assertEqual(r.missing[0]["count"], 2)
        self.assertEqual(r.missing[0]["exact"], [120, 121])

    def _unreadable_neighbor(self, printed_unreadable):
        # 印字 120 が欠け、その隣のページが読めない。
        # 章扉の直前の欠けとノンブルの並びが同じで、番号だけでは区別できない。
        # 既定は疑い(suspect_blank_removed)として報告し、strict で欠け扱いにする。
        pr = book(total=299, skip={120})
        pdf = [k for k, v in pr.items() if v == [printed_unreadable]][0]
        pr[pdf] = []
        return make(299, pr)

    def _check_unreadable_neighbor(self, pages):
        r = analyze(pages)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.missing, [])
        self.assertEqual(len(r.suspect_blank_removed), 1)
        g = r.suspect_blank_removed[0]
        self.assertEqual(g["count"], 1)
        self.assertIsNone(g["exact"])
        self.assertLessEqual(g["printed_from"], 120)
        self.assertGreaterEqual(g["printed_to"], 120)
        r2 = analyze(pages, strict=True)
        self.assertEqual(r2.status, "missing")
        self.assertIn("suspect_blank_removed", r2.gating)

    def test_missing_with_unreadable_neighbor_after(self):
        self._check_unreadable_neighbor(self._unreadable_neighbor(121))

    def test_missing_with_unreadable_neighbor_before(self):
        self._check_unreadable_neighbor(self._unreadable_neighbor(119))

    def test_one_unreadable_page(self):
        pr = book()
        pr[100] = []
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.missing, [])

    def test_one_misread_page(self):
        pr = book()
        pr[163] = [168]  # 印字 158 を 168 と誤読
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.missing, [])

    def test_chapter_openers(self):
        pr = book()
        openers = [30, 80, 130, 180, 230]
        for o in openers:
            pr[o] = []
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.unnumbered_in_body, openers)

    def test_inserted_pages(self):
        # 図版 2 枚(番号なし)を印字 99 と 100 の間に差し込む
        pr = {}
        for pdf in range(5, 300):
            if pdf <= 103:
                pr[pdf] = [pdf - 4]  # 印字 1..99
            elif pdf in (104, 105):
                pr[pdf] = []
            else:
                pr[pdf] = [pdf - 6]  # 印字 100..
        r = analyze(make(299, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(r.extra_pages), 1)
        self.assertEqual(r.extra_pages[0]["count"], 2)

    def test_duplicate_scan(self):
        pr = {}
        for pdf in range(5, 300):
            if pdf <= 104:
                pr[pdf] = [pdf - 4]  # 印字 1..100
            else:
                pr[pdf] = [pdf - 5]  # PDF 105 は印字 100 の重複
        r = analyze(make(299, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(r.duplicates), 1)
        self.assertEqual(r.duplicates[0]["printed"], 100)
        self.assertEqual(r.duplicates[0]["pdf_pages"], [104, 105])

    def test_swapped_pages(self):
        pr = book()
        pr[150], pr[151] = pr[151], pr[150]
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(r.order_suspects), 2)
        self.assertEqual({o["pdf_page"] for o in r.order_suspects}, {150, 151})

    def test_chapter_number_noise(self):
        pr = book()
        for pdf in range(120, 140):
            pr[pdf] = pr[pdf] + [8]
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.missing, [])
        self.assertEqual(r.extra_pages, [])

    def test_suspect_blank_removed_before_chapter_opener(self):
        # 印字 22 の白紙が消え、印字 23 は章扉(番号なし)
        pr = book(total=299, skip={22})
        pdf23 = [k for k, v in pr.items() if v == [24]][0] - 1
        pr[pdf23] = []  # 章扉(隠しノンブル)
        # 印字 23 の章扉は PDF 上では印字 24 の 1 つ前にある
        r = analyze(make(299, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(r.suspect_blank_removed), 1)
        self.assertEqual(r.missing, [])
        r2 = analyze(make(299, pr), strict=True)
        self.assertEqual(r2.status, "missing")
        self.assertEqual(r2.gating, ["suspect_blank_removed"])

    def test_uncertain_when_barely_readable(self):
        pr = {pdf: v for pdf, v in book().items() if pdf % 10 == 0}
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "uncertain")
        self.assertEqual(r.gating, ["uncertain"])

    def test_no_numbers_is_uncertain(self):
        r = analyze(make(50, {}))
        self.assertEqual(r.status, "uncertain")
        self.assertEqual(r.segments, [])

    def test_back_matter(self):
        pr = book(total=300)
        for pdf in range(296, 301):
            pr[pdf] = []
        r = analyze(make(300, pr))
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.back_matter, [296, 300])

    def test_blank_pages_and_to_dict(self):
        r = analyze(make(300, book(), blank={2, 3}))
        self.assertEqual(r.blank_pages, [2, 3])
        d = r.to_dict()
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["segments"][0]["count"], 296)
        self.assertEqual(d["coverage"], round(296 / 300, 3))

    def test_invalid_pages_raise(self):
        with self.assertRaises(ValueError):
            analyze([PageObs(2, [1])])


if __name__ == "__main__":
    unittest.main()
