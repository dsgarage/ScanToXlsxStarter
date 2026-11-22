"""common.backup_existing のテスト。"""
import tempfile
import unittest
from pathlib import Path

from ocr_toolkit.book2md.common import backup_existing


class BackupExistingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.dest = self.dir / "本.md"
        self.bk = self.dir / "backup"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_dest(self):
        self.assertIsNone(backup_existing(self.dest, self.bk, b"new"))
        self.assertFalse(self.bk.exists())

    def test_same_content(self):
        self.dest.write_bytes(b"same")
        self.assertIsNone(backup_existing(self.dest, self.bk, b"same"))
        self.assertEqual(self.dest.read_bytes(), b"same")
        self.assertFalse(self.bk.exists())

    def test_different_content(self):
        self.dest.write_bytes(b"old")
        moved = backup_existing(self.dest, self.bk, b"new")
        self.assertFalse(self.dest.exists())
        files = list(self.bk.iterdir())
        self.assertEqual(files, [moved])
        self.assertEqual(moved.read_bytes(), b"old")
        self.assertTrue(moved.name.startswith("本.") and moved.name.endswith(".md"))

    def test_same_second_does_not_overwrite(self):
        self.dest.write_bytes(b"v1")
        backup_existing(self.dest, self.bk, b"x")
        self.dest.write_bytes(b"v2")
        backup_existing(self.dest, self.bk, b"x")
        files = list(self.bk.iterdir())
        self.assertEqual(len(files), 2)
        self.assertEqual(sorted(f.read_bytes() for f in files), [b"v1", b"v2"])


if __name__ == "__main__":
    unittest.main()
