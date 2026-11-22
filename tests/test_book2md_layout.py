import unittest

from ocr_toolkit.book2md.layout import (
    Box,
    band_of,
    build_paragraphs,
    collect_running_heads,
    count_unread,
    filter_ruby,
    header_key,
    order_lines,
    page_orientation,
    page_to_text,
    split_tiers,
    strip_margins,
    to_boxes,
)

W, H = 1000, 2000


def ocr_page(items, w=W, h=H):
    """items = [(text, (x0, y0, x1, y1)), ...]"""
    return {
        "w": w,
        "h": h,
        "texts": [t for t, _ in items],
        "scores": [0.99] * len(items),
        "boxes": [list(b) for _, b in items],
    }


def col(x0, y0, y1, text, width=40):
    return (text, (x0, y0, x0 + width, y1))


class BoxesTest(unittest.TestCase):
    def test_to_boxes_filters(self):
        o = {
            "texts": ["あ", " ", "い", ""],
            "scores": [0.9, 0.9, 0.3, 0.9],
            "boxes": [[0, 0, 1, 1]] * 4,
        }
        self.assertEqual([b.text for b in to_boxes(o)], ["あ"])

    def test_orientation(self):
        v = [Box(0, 0, 40, 500, "あいうえお", 1)]
        h = [Box(0, 0, 500, 40, "あいうえお", 1)]
        self.assertEqual(page_orientation(v), "vertical")
        self.assertEqual(page_orientation(h), "horizontal")
        self.assertEqual(page_orientation([]), "empty")

    def test_band_and_header_key(self):
        self.assertEqual(band_of(Box(0, 10, 50, 100, "x", 1), 2000), "top")
        self.assertEqual(band_of(Box(0, 1800, 50, 1900, "x", 1), 2000), "bottom")
        self.assertIsNone(band_of(Box(0, 800, 50, 900, "x", 1), 2000))
        self.assertEqual(header_key("12 | テスト書名 ・ 第３章"), "テスト書名第章")


class MarginTest(unittest.TestCase):
    def test_running_heads_and_nombre_removed(self):
        def page(n):
            return [
                Box(100, 50, 500, 100, f"テスト書名 {n}", 1),
                Box(100, 800, 500, 840, "本文です", 1),
            ]

        pages = [(page(i), H, "horizontal") for i in (1, 2, 3)]
        heads = collect_running_heads(pages)
        self.assertEqual(heads, {"テスト書名"})
        # 2 ページだけなら柱とみなさない
        self.assertEqual(collect_running_heads(pages[:2]), set())

        boxes = page(4) + [Box(450, 1850, 520, 1890, "275", 1)]
        kept, removed = strip_margins(boxes, H, "horizontal", heads)
        self.assertEqual([b.text for b in kept], ["本文です"])
        self.assertEqual(removed, 2)

    def test_vertical_narrow_header_kept(self):
        # 縦書きページで縦長の箱は柱として除かない
        heads = {"テスト書名"}
        b = Box(900, 50, 940, 230, "テスト書名", 1)
        kept, removed = strip_margins([b], H, "vertical", heads)
        self.assertEqual(len(kept), 1)
        self.assertEqual(removed, 0)

    def test_body_number_not_in_band_kept(self):
        b = Box(100, 800, 160, 840, "275", 1)
        kept, _ = strip_margins([b], H, "horizontal", set())
        self.assertEqual(len(kept), 1)


class RubyTest(unittest.TestCase):
    def test_ruby_removed(self):
        main = Box(700, 300, 740, 800, "漢字の本文です", 1)
        ruby = Box(745, 300, 760, 360, "かんじ", 1)
        thin_kanji = Box(600, 300, 615, 360, "漢字", 1)
        kept, removed = filter_ruby([main, ruby, thin_kanji], "vertical")
        self.assertEqual(removed, 1)
        self.assertEqual([b.text for b in kept], ["漢字の本文です", "漢字"])

    def test_no_base_boxes_no_op(self):
        b = Box(0, 0, 10, 50, "あい", 1)
        kept, removed = filter_ruby([b], "vertical")
        self.assertEqual((len(kept), removed), (1, 0))


class VerticalTest(unittest.TestCase):
    def test_three_columns_right_to_left(self):
        o = ocr_page([
            col(500, 300, 800, "さしすせそ"),
            col(700, 300, 800, "あいうえお"),
            col(600, 300, 800, "かきくけこ"),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.orientation, "vertical")
        self.assertEqual(r.paragraphs, ["あいうえおかきくけこさしすせそ"])
        self.assertEqual(r.stats["lines"], 3)

    def test_two_tiers_top_first(self):
        o = ocr_page([
            col(700, 300, 800, "上段右です"),
            col(600, 300, 800, "上段左です"),
            col(700, 900, 1400, "下段右です"),
            col(600, 900, 1400, "下段左です"),
        ])
        tiers = split_tiers(to_boxes(o), "vertical", H)
        self.assertEqual(len(tiers), 2)
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs[0].startswith("上段右です上段左です"), True)
        self.assertEqual("".join(r.paragraphs), "上段右です上段左です下段右です下段左です")

    def test_indent_splits_paragraph(self):
        o = ocr_page([
            col(700, 300, 800, "あいうえお"),
            col(600, 360, 800, "かきくけこ"),
            col(500, 300, 800, "さしすせそ"),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs, ["あいうえお", "かきくけこさしすせそ"])

    def test_short_line_splits_paragraph(self):
        o = ocr_page([
            col(700, 300, 800, "あいうえお"),
            col(600, 300, 500, "かきく"),
            col(500, 300, 800, "さしすせそ"),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs, ["あいうえおかきく", "さしすせそ"])

    def test_quote_after_sentence_end_splits(self):
        o = ocr_page([
            col(700, 300, 800, "あいうえお。"),
            col(600, 300, 800, "「かきくけこ」"),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs, ["あいうえお。", "「かきくけこ」"])

    def test_keep_lines(self):
        o = ocr_page([
            col(700, 300, 800, "あいうえお"),
            col(600, 300, 800, "かきくけこ"),
        ])
        r = page_to_text(o, set(), keep_lines=True)
        self.assertEqual(r.paragraphs, ["あいうえお", "かきくけこ"])

    def test_ruby_and_nombre_removed_in_page(self):
        o = ocr_page([
            col(700, 300, 800, "漢字の本文です"),
            ("かんじ", (745, 300, 760, 360)),
            ("12", (480, 1850, 540, 1890)),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs, ["漢字の本文です"])
        self.assertEqual(r.stats["removed_ruby"], 1)
        self.assertEqual(r.stats["removed_margin"], 1)

    def test_empty_page(self):
        r = page_to_text(ocr_page([]), set())
        self.assertEqual((r.orientation, r.paragraphs), ("empty", []))


class HorizontalTest(unittest.TestCase):
    def test_lines_joined_and_ordered(self):
        o = ocr_page([
            ("これは", (100, 300, 300, 340)),
            ("テスト", (310, 302, 500, 342)),
            ("次の行です", (100, 360, 500, 400)),
        ])
        boxes = to_boxes(o)
        lines = order_lines(boxes, "horizontal")
        self.assertEqual([ln.text for ln in lines], ["これはテスト", "次の行です"])

    def test_ascii_words_spaced(self):
        o = ocr_page([
            ("Hello", (100, 300, 300, 340)),
            ("World", (310, 300, 500, 340)),
            ("あいうえおかきくけこ", (100, 360, 500, 400)),
        ])
        lines = order_lines(to_boxes(o), "horizontal")
        self.assertEqual(lines[0].text, "Hello World")

    def test_indent_splits_paragraph(self):
        o = ocr_page([
            ("最初の段落の行です", (100, 300, 900, 340)),
            ("字下げの行です", (160, 360, 900, 400)),
            ("続きの行です", (100, 420, 900, 460)),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.orientation, "horizontal")
        self.assertEqual(r.paragraphs, ["最初の段落の行です", "字下げの行です続きの行です"])

    def test_short_line_splits_paragraph(self):
        o = ocr_page([
            ("最初の段落の行です", (100, 300, 900, 340)),
            ("短い行", (100, 360, 400, 400)),
            ("次の段落です", (100, 420, 900, 460)),
        ])
        r = page_to_text(o, set())
        self.assertEqual(r.paragraphs, ["最初の段落の行です短い行", "次の段落です"])

    def test_build_paragraphs_empty(self):
        self.assertEqual(build_paragraphs([], "horizontal"), [])


class RunSplitTest(unittest.TestCase):
    """見出しや別の位置のまとまりがあっても、本文の段落判定がずれないこと。"""

    def test_horizontal_heading_and_body(self):
        items = [
            ("見出しの一行目です", (300, 600, 700, 640)),
            ("見出しの二行目です", (300, 660, 700, 700)),
        ]
        for k in range(5):
            x1 = 500 if k == 4 else 900
            items.append((f"本文の{k}行目", (100, 1000 + k * 28, x1, 1018 + k * 28)))
        r = page_to_text(ocr_page(items), set())
        self.assertEqual(r.orientation, "horizontal")
        self.assertEqual(len(r.paragraphs), 2)
        self.assertEqual(r.paragraphs[0], "見出しの一行目です見出しの二行目です")
        self.assertEqual(r.paragraphs[1], "本文の0行目本文の1行目本文の2行目本文の3行目本文の4行目")

    def test_horizontal_two_paragraphs(self):
        items = [
            ("最初の行です", (100, 1000, 900, 1018)),
            ("次の行です", (100, 1028, 900, 1046)),
            ("字下げの行です", (118, 1056, 900, 1074)),
            ("続きの行です", (100, 1084, 900, 1102)),
        ]
        r = page_to_text(ocr_page(items), set())
        self.assertEqual(r.paragraphs, ["最初の行です次の行です", "字下げの行です続きの行です"])

    def test_vertical_short_then_indent(self):
        items = []
        for k in range(6):
            y0, y1 = 300, 800
            if k == 2:
                y1 = 500
            if k == 3:
                y0 = 360
            items.append(col(800 - k * 60, y0, y1, f"本文{k}行目です"))
        r = page_to_text(ocr_page(items), set())
        self.assertEqual(r.orientation, "vertical")
        self.assertEqual(
            r.paragraphs,
            ["本文0行目です本文1行目です本文2行目です", "本文3行目です本文4行目です本文5行目です"],
        )

    def test_vertical_heading_and_body(self):
        items = [
            col(800, 300, 700, "見出しの題", width=80),
            col(600, 300, 800, "本文一行目です"),
            col(540, 300, 800, "本文二行目です"),
            col(480, 300, 800, "本文三行目です"),
        ]
        r = page_to_text(ocr_page(items), set())
        self.assertEqual(r.paragraphs, ["見出しの題", "本文一行目です本文二行目です本文三行目です"])

    def test_vertical_two_separated_runs(self):
        items = [
            col(800, 300, 800, "右の一行目です"),
            col(740, 300, 800, "右の二行目です"),
            col(400, 300, 800, "左の一行目です"),
            col(340, 300, 800, "左の二行目です"),
        ]
        r = page_to_text(ocr_page(items), set())
        self.assertEqual(r.paragraphs, ["右の一行目です右の二行目です", "左の一行目です左の二行目です"])


class CountUnreadTest(unittest.TestCase):
    def test_counts_only_long_empty_boxes(self):
        o = ocr_page([
            ("", (100, 100, 140, 1100)),  # 長い空の箱 → 数える
            ("  ", (200, 100, 240, 1100)),  # 空白だけも空扱い
            ("", (300, 100, 340, 200)),  # 短い空の箱
            ("", (400, 100, 800, 300)),  # 長辺が短辺の 3 倍未満
            ("あいうえお", (500, 100, 540, 1100)),  # 文字のある箱
        ])
        self.assertEqual(count_unread(o), 2)

    def test_empty_page(self):
        self.assertEqual(count_unread(ocr_page([])), 0)


if __name__ == "__main__":
    unittest.main()
