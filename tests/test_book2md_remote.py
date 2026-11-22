import argparse
import io
import contextlib
import tarfile
import tempfile
import unittest
from pathlib import Path

from ocr_toolkit.book2md import remote
from ocr_toolkit.book2md.remote import (
    cmd_book2md_remote,
    decide_todo,
    make_code_tarball,
    ps_quote,
    remote_run_ps,
    scp_down,
    scp_up,
    ssh_cmd,
)

REPO = Path(__file__).resolve().parents[1]


def _args(**kw):
    d = dict(input="", host="winpc", setup=False, dry_run=True, device="auto", model="auto",
             on_uncertain="ocr", strict=False, apply_fix=False, keep_lines=False, include_pgx=False)
    d.update(kw)
    return argparse.Namespace(**d)


class QuoteAndCmdTest(unittest.TestCase):
    def test_ps_quote(self):
        self.assertEqual(ps_quote("abc"), "'abc'")
        self.assertEqual(ps_quote("it's"), "'it''s'")

    def test_ssh_cmd_shape(self):
        c = ssh_cmd("winpc", "Get-Date")
        self.assertEqual(c[0], "ssh")
        self.assertEqual(c[-2], "winpc")
        self.assertTrue(c[-1].startswith(remote.PS_PREAMBLE))
        self.assertTrue(c[-1].endswith("Get-Date"))
        self.assertIn("BatchMode=yes", c)
        self.assertIn("[Console]::OutputEncoding", c[-1])

    def test_scp(self):
        up = scp_up("winpc", Path("/a b/x.pdf"), "book2md/inbox/x.pdf")
        self.assertEqual(up[:2], ["scp", "-q"])
        self.assertEqual(up[-2:], ["/a b/x.pdf", "winpc:book2md/inbox/x.pdf"])
        down = scp_down("winpc", "book2md/out/r.json", Path("/t/r.json"))
        self.assertEqual(down[-2:], ["winpc:book2md/out/r.json", "/t/r.json"])


class RunPsTest(unittest.TestCase):
    def test_ascii_only(self):
        ps = remote_run_ps(["1a2b3c4d5e6f", "aaaaaaaaaaaa"], "20261122_180000", _args())
        self.assertTrue(all(ord(ch) < 128 for ch in ps))
        self.assertIn(r"inbox\1a2b3c4d5e6f.pdf inbox\aaaaaaaaaaaa.pdf", ps)
        self.assertIn("--no-rename-missing", ps)
        self.assertIn(r"--report out\report_20261122_180000.json", ps)
        self.assertTrue(ps.endswith("exit $LASTEXITCODE"))

    def test_fix_flag(self):
        off = remote_run_ps(["a"], "r", _args(apply_fix=False))
        on = remote_run_ps(["a"], "r", _args(apply_fix=True))
        self.assertNotIn("--fix", off)
        self.assertNotIn("--no-fix", on)
        self.assertIn(" --fix", on)

    def test_other_flags(self):
        ps = remote_run_ps(["a"], "r", _args(strict=True, keep_lines=True, device="cpu",
                                             model="mobile", on_uncertain="skip"))
        for s in (" --strict", " --keep-lines", "--device cpu", "--model mobile", "--on-uncertain skip"):
            self.assertIn(s, ps)
        plain = remote_run_ps(["a"], "r", _args())
        self.assertNotIn("--strict", plain)
        self.assertNotIn("--keep-lines", plain)


class CheckOnlyPsTest(unittest.TestCase):
    def test_check_only_flag(self):
        on = remote_run_ps(["a"], "r", _args(check_only=True))
        off = remote_run_ps(["a"], "r", _args())
        self.assertIn(" --check-only", on)
        self.assertNotIn("--check-only", off)
        self.assertNotIn("--check-only", remote_run_ps(["a"], "r", _args(check_only=False)))


class DecideTodoTest(unittest.TestCase):
    def test_done_and_todo(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            a, b, c = folder / "a b.pdf", folder / "b.pdf", folder / "c.pdf"
            for p in (a, b, c):
                p.write_bytes(b"x")
            (folder / "a b.md").write_text("m")
            # c は状態が ok でも MD が無いので再処理
            state = {
                "ja": {"status": "ok"},
                "jb": {"status": "missing"},
                "jc": {"status": "ok_unchecked"},
            }
            todo, done = decide_todo([(a, "ja"), (b, "jb"), (c, "jc")], state, folder)
            self.assertEqual([j for _, j in done], ["ja"])
            self.assertEqual([j for _, j in todo], ["jb", "jc"])

    def test_path_input_computes_job_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.pdf"
            p.write_bytes(b"hello")
            todo, done = decide_todo([p], {}, Path(td))
            self.assertEqual(len(todo), 1)
            self.assertEqual(len(todo[0][1]), 12)
            self.assertEqual(done, [])


class TarballTest(unittest.TestCase):
    def test_contents(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "ocr_toolkit" / "book2md" / "__pycache__").mkdir(parents=True)
            (repo / "scripts").mkdir()
            (repo / "ocr_toolkit" / "cli.py").write_text("x")
            (repo / "ocr_toolkit" / "book2md" / "remote.py").write_text("x")
            (repo / "ocr_toolkit" / "book2md" / "mod.pyc").write_bytes(b"x")
            (repo / "ocr_toolkit" / "book2md" / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"x")
            (repo / "ocr_toolkit" / ".DS_Store").write_bytes(b"x")
            (repo / "scripts" / "setup_windows.ps1").write_text("x")
            (repo / "scripts" / "other.py").write_text("x")
            dest = Path(td) / "app.tgz"
            make_code_tarball(repo, dest)
            with tarfile.open(dest) as tf:
                names = tf.getnames()
            self.assertIn("ocr_toolkit/cli.py", names)
            self.assertIn("ocr_toolkit/book2md/remote.py", names)
            self.assertIn("scripts/setup_windows.ps1", names)
            self.assertNotIn("scripts/other.py", names)
            self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")
                              or n.endswith(".DS_Store")])

    def test_real_repo(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "app.tgz"
            make_code_tarball(REPO, dest)
            with tarfile.open(dest) as tf:
                names = tf.getnames()
            self.assertTrue(any(n.startswith("ocr_toolkit/") for n in names))
            self.assertIn("scripts/setup_windows.ps1", names)
            self.assertFalse([n for n in names if "__pycache__" in n or n.endswith(".pyc")])


class MiscTest(unittest.TestCase):
    def test_inbox_listing(self):
        self.assertEqual(remote._parse_inbox_listing(""), {})
        self.assertEqual(remote._parse_inbox_listing('{"Name":"a.pdf","Length":5}'), {"a.pdf": 5})
        self.assertEqual(
            remote._parse_inbox_listing('[{"Name":"a.pdf","Length":5},{"Name":"b.pdf","Length":6}]'),
            {"a.pdf": 5, "b.pdf": 6})

    def test_int_keys(self):
        c = remote._int_keys({"printed_by_pdf": {"5": 1, "6": 2}})
        self.assertEqual(c["printed_by_pdf"], {5: 1, 6: 2})
        self.assertIsNone(remote._int_keys(None))

    def test_dry_run_does_not_communicate(self):
        calls = []
        orig_run, orig_sub = remote._run, remote.subprocess.run
        remote._run = lambda *a, **k: calls.append(a) or None
        remote.subprocess.run = lambda *a, **k: calls.append(a) or None
        try:
            with tempfile.TemporaryDirectory() as td:
                folder = Path(td) / "日本語 フォルダ"
                folder.mkdir()
                (folder / "本 A.pdf").write_bytes(b"aaa")
                (folder / "PGX_本 B.pdf").write_bytes(b"bbb")
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = cmd_book2md_remote(_args(input=str(folder)))
                out = buf.getvalue()
        finally:
            remote._run, remote.subprocess.run = orig_run, orig_sub
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        self.assertIn("本 A.pdf", out)
        self.assertIn("PGX_本 B.pdf", out)


if __name__ == "__main__":
    unittest.main()


class CollectBackupTest(unittest.TestCase):
    def test_existing_md_is_backed_up(self):
        orig_run = remote._run
        orig_fetch = remote._fetch_check

        def fake_run(cmd, what):
            Path(cmd[-1]).write_text("新しいダミー", encoding="utf-8")

        remote._run = fake_run
        remote._fetch_check = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as td:
                folder = Path(td)
                state = folder / "_book2md"
                state.mkdir()
                pdf = folder / "本.pdf"
                pdf.write_bytes(b"x")
                (folder / "本.md").write_text("校正済みのダミー", encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    book = remote._collect_book("winpc", pdf, "abc", {"status": "ok"}, folder, state)
                self.assertEqual(book["status"], "ok")
                self.assertEqual((folder / "本.md").read_text(encoding="utf-8"), "新しいダミー")
                files = list((state / "backup").iterdir())
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0].read_text(encoding="utf-8"), "校正済みのダミー")
        finally:
            remote._run, remote._fetch_check = orig_run, orig_fetch


class CollectCheckOnlyTest(unittest.TestCase):
    def _collect(self, status, check_only):
        orig_run, orig_fetch = remote._run, remote._fetch_check
        fetched = []
        remote._run = lambda cmd, what: None
        remote._fetch_check = lambda *a, **k: fetched.append(a)
        try:
            with tempfile.TemporaryDirectory() as td:
                folder = Path(td)
                state = folder / "_book2md"
                state.mkdir()
                pdf = folder / "本.pdf"
                pdf.write_bytes(b"x")
                with contextlib.redirect_stdout(io.StringIO()):
                    book = remote._collect_book("winpc", pdf, "abc", {"status": status}, folder, state,
                                                check_only=check_only)
                return book, pdf.exists(), (folder / "PGX_本.pdf").exists(), (folder / "本.md").exists(), len(fetched)
        finally:
            remote._run, remote._fetch_check = orig_run, orig_fetch

    def test_missing_check_only_does_not_rename(self):
        book, pdf_exists, pgx_exists, md_exists, n = self._collect("missing", True)
        self.assertEqual(book["status"], "missing")
        self.assertTrue(pdf_exists)
        self.assertFalse(pgx_exists)
        self.assertEqual(n, 1)

    def test_missing_normal_renames(self):
        book, pdf_exists, pgx_exists, md_exists, n = self._collect("missing", False)
        self.assertFalse(pdf_exists)
        self.assertTrue(pgx_exists)

    def test_checked_statuses_fetch_check_only(self):
        for st in ("checked_ok", "checked_uncertain"):
            book, pdf_exists, pgx_exists, md_exists, n = self._collect(st, True)
            self.assertEqual(book["status"], st)
            self.assertTrue(pdf_exists)
            self.assertFalse(md_exists)
            self.assertEqual(n, 1)
