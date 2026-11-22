"""book2md の Air 側の入口(ssh/scp。標準ライブラリのみ)

Air のシステムの python3 で動かすため、標準ライブラリと .common / .report だけを import する。
Windows(ssh ホスト winpc)へコードと PDF を送り、本体を実行して MD とレポートを取ってくる。
日本語・空白を含むファイル名は Windows に渡さない(パスは ASCII の job_id だけ)。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from .common import (
    STATUS_CHECKED_OK,
    STATUS_CHECKED_UNCERTAIN,
    PGX_PREFIX,
    STATUS_FAILED,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_OK_UNCHECKED,
    STATUS_SKIPPED_DONE,
    STATUS_SKIPPED_PGX,
    atomic_write_json,
    atomic_write_text,
    backup_existing,
    job_id_for,
    pgx_name,
    read_json,
)
from .report import build_report, render_text

REMOTE_BASE = "book2md"  # 遠隔(Windows)のホームからの相対
SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=6",
]
# winpc の ssh の既定シェルは PowerShell。出力の文字化けを防ぐ
PS_PREAMBLE = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; "
    "Set-Location $HOME; "
)

EXIT_SETUP_NEEDED = 2
EXIT_REMOTE_INCOMPLETE = 3
EXIT_INTERRUPTED = 130


def ps_quote(s: str) -> str:
    """PowerShell の単一引用符文字列にする。"""
    return "'" + s.replace("'", "''") + "'"


def ssh_cmd(host: str, ps: str) -> list[str]:
    return ["ssh", *SSH_OPTS, host, PS_PREAMBLE + ps]


def scp_up(host: str, local: Path, remote_rel: str) -> list[str]:
    return ["scp", "-q", *SSH_OPTS, str(local), f"{host}:{remote_rel}"]


def scp_down(host: str, remote_rel: str, local: Path) -> list[str]:
    return ["scp", "-q", *SSH_OPTS, f"{host}:{remote_rel}", str(local)]


def _tar_filter(info: tarfile.TarInfo):
    parts = info.name.split("/")
    base = parts[-1]
    if "__pycache__" in parts or base.endswith(".pyc") or base == ".DS_Store":
        return None
    return info


def make_code_tarball(repo_root: Path, dest: Path) -> None:
    """ocr_toolkit/** と scripts/setup_windows.ps1 を tar.gz にする。"""
    repo_root = Path(repo_root)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(repo_root / "ocr_toolkit", arcname="ocr_toolkit", filter=_tar_filter)
        tf.add(
            repo_root / "scripts" / "setup_windows.ps1",
            arcname="scripts/setup_windows.ps1",
            filter=_tar_filter,
        )


def remote_run_ps(job_ids: list[str], run_id: str, o) -> str:
    """winpc で本体を実行する PowerShell。ASCII だけで組み立てる。"""
    device = getattr(o, "device", "auto")
    model = getattr(o, "model", "auto")
    on_uncertain = getattr(o, "on_uncertain", "ocr")
    ps = (
        "$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUNBUFFERED='1'; "
        "$env:PYTHONPATH=(Join-Path $HOME 'book2md\\app'); Set-Location (Join-Path $HOME 'book2md'); "
        "& (Join-Path $HOME 'book2md\\venv\\Scripts\\python.exe') -m ocr_toolkit.cli book2md "
        + " ".join(f"inbox\\{j}.pdf" for j in job_ids)
        + f" --work work --out out --no-rename-missing --report out\\report_{run_id}.json"
        + f" --device {device} --model {model} --on-uncertain {on_uncertain}"
        + (" --strict" if getattr(o, "strict", False) else "")
        + (" --fix" if getattr(o, "apply_fix", False) else "")
        + (" --keep-lines" if getattr(o, "keep_lines", False) else "")
        + (" --check-only" if getattr(o, "check_only", False) else "")
        + "; exit $LASTEXITCODE"
    )
    return ps


def decide_todo(pdfs, state: dict, folder: Path) -> tuple[list, list]:
    """(今回処理する [(pdf, job_id)], 済みで飛ばす [(pdf, job_id)])。

    pdfs の要素は (Path, job_id) か Path(その場で job_id を計算)。
    済み = state[job_id]["status"] が ok/ok_unchecked かつ folder/<stem>.md が存在。
    """
    todo: list = []
    done: list = []
    for item in pdfs:
        if isinstance(item, tuple):
            pdf, jid = item
        else:
            pdf, jid = item, job_id_for(item)
        st = (state.get(jid) or {}).get("status")
        if st in (STATUS_OK, STATUS_OK_UNCHECKED) and (Path(folder) / f"{pdf.stem}.md").exists():
            done.append((pdf, jid))
        else:
            todo.append((pdf, jid))
    return todo, done


def _int_keys(check):
    """JSON 経由で文字列になった check.printed_by_pdf のキーを整数に戻す。"""
    if isinstance(check, dict) and isinstance(check.get("printed_by_pdf"), dict):
        check["printed_by_pdf"] = {int(k): v for k, v in check["printed_by_pdf"].items()}
    return check


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(f"[book2md] {msg}", flush=True)


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    """通信コマンドを実行する(出力は取り込む)。失敗したら stderr つきで例外。"""
    r = subprocess.run(
        cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"{what} に失敗しました (exit {r.returncode}): {(r.stderr or '').strip()}")
    return r


def _list_inputs(path: Path, include_pgx: bool) -> tuple[Path, list[Path], list[Path]]:
    """(状態フォルダの親, 対象 PDF, 飛ばす PGX)。"""
    if path.is_dir():
        folder = path
        pdfs = sorted(
            (p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
            key=lambda p: p.name,
        )
    else:
        folder = path.parent
        pdfs = [path]
    target = [p for p in pdfs if include_pgx or not p.name.startswith(PGX_PREFIX)]
    skipped = [p for p in pdfs if not (include_pgx or not p.name.startswith(PGX_PREFIX))]
    return folder, target, skipped


def _parse_inbox_listing(text: str) -> dict:
    """Get-ChildItem | ConvertTo-Json の結果(0 件・1 件=dict・複数=list)を {名前: サイズ} にする。"""
    text = (text or "").strip().lstrip("\ufeff")
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if isinstance(data, dict):
        data = [data]
    return {d["Name"]: d["Length"] for d in data if isinstance(d, dict) and "Name" in d}


def _skip_book(pdf: Path, jid: str, status: str, state: dict, folder: Path) -> dict:
    return {
        "job_id": jid, "name": pdf.name, "source": str(pdf),
        "pages": (state.get(jid) or {}).get("pages"), "status": status,
        "md": str(folder / f"{pdf.stem}.md") if status == STATUS_SKIPPED_DONE else None,
        "renamed_to": None, "error": None, "check": None, "ocr": None, "elapsed_sec": None,
    }


def cmd_book2md_remote(args) -> int:
    try:
        return _main(args)
    except KeyboardInterrupt:
        print("\n中断しました。同じコマンドで続きから再開できます", flush=True)
        return EXIT_INTERRUPTED
    except RuntimeError as e:
        print(f"[book2md] {e}", file=sys.stderr, flush=True)
        return 1


def _main(args) -> int:
    started = _now()
    host = getattr(args, "host", "winpc")
    include_pgx = getattr(args, "include_pgx", False)
    src = Path(args.input).expanduser()
    if not src.exists():
        print(f"[book2md] 入力が見つかりません: {src}", file=sys.stderr)
        return 2

    # 1. 入力の列挙
    folder, targets, skipped_pgx = _list_inputs(src.resolve(), include_pgx)
    # 2. 状態
    state_dir = folder / "_book2md"
    state_path = state_dir / "state.json"
    state = read_json(state_path, {}) or {}
    # 3. job_id と todo
    pairs: list = []
    seen: set[str] = set()
    for p in targets:
        jid = job_id_for(p)
        if jid in seen:
            _log(f"同じ内容の PDF を飛ばします: {p.name}")
            continue
        seen.add(jid)
        pairs.append((p, jid))
    todo, done = decide_todo(pairs, state, folder)

    if getattr(args, "dry_run", False):
        print("処理する:")
        for p, jid in todo:
            print(f"  {jid}  {p.name}")
        print("飛ばす(済み):")
        for p, jid in done:
            print(f"  {jid}  {p.name}")
        print("飛ばす(PGX_):")
        for p in skipped_pgx:
            print(f"  {p.name}")
        return 0

    # 4. 遠隔のフォルダ
    _run(ssh_cmd(host, "New-Item -ItemType Directory -Force book2md\\inbox, book2md\\work, "
                       "book2md\\out, book2md\\app | Out-Null"), "遠隔フォルダの作成")

    # 5. コード同期(古いファイルを残さないため、展開前に app\ocr_toolkit と app\scripts を消す)
    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as td:
        tgz = Path(td) / "app.tgz"
        make_code_tarball(repo_root, tgz)
        _log("コードを同期します")
        _run(scp_up(host, tgz, f"{REMOTE_BASE}/app.tgz"), "コードの転送")
    _run(ssh_cmd(host,
                 "if (Test-Path book2md\\app\\ocr_toolkit) { Remove-Item -Recurse -Force book2md\\app\\ocr_toolkit }; "
                 "if (Test-Path book2md\\app\\scripts) { Remove-Item -Recurse -Force book2md\\app\\scripts }; "
                 "tar -xzf book2md/app.tgz -C book2md/app; exit $LASTEXITCODE"), "コードの展開")

    # 6. 環境導入
    if getattr(args, "setup", False):
        device = getattr(args, "device", "auto")
        r = subprocess.run(
            ssh_cmd(host, "powershell -NoProfile -ExecutionPolicy Bypass -File "
                          f"book2md\\app\\scripts\\setup_windows.ps1 -Device {device}; exit $LASTEXITCODE"),
            stdin=subprocess.DEVNULL, check=False)
        return r.returncode

    # 7. venv の確認
    r = _run(ssh_cmd(host, "Test-Path book2md\\venv\\Scripts\\python.exe"), "環境の確認")
    if r.stdout.strip() != "True":
        print("[book2md] 先に --setup を実行してください", file=sys.stderr)
        return EXIT_SETUP_NEEDED

    results: list[dict] = []
    if todo:
        # 8. 転送
        r = _run(ssh_cmd(host, "Get-ChildItem book2md\\inbox -Filter *.pdf | "
                               "Select-Object Name,Length | ConvertTo-Json -Compress"), "inbox の確認")
        existing = _parse_inbox_listing(r.stdout)
        with tempfile.TemporaryDirectory() as td:
            for pdf, jid in todo:
                if existing.get(f"{jid}.pdf") != pdf.stat().st_size:
                    _log(f"転送: {jid} = {pdf.name}")
                    _run(scp_up(host, pdf.resolve(), f"{REMOTE_BASE}/inbox/{jid}.pdf"), "PDF の転送")
                side = Path(td) / f"{jid}.json"
                side.write_text(json.dumps({"name": pdf.name}, ensure_ascii=False), encoding="utf-8")
                _run(scp_up(host, side, f"{REMOTE_BASE}/inbox/{jid}.json"), "名前ファイルの転送")

        # 9. 遠隔実行(出力はそのまま流す)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        subprocess.run(ssh_cmd(host, remote_run_ps([j for _, j in todo], run_id, args)),
                       stdin=subprocess.DEVNULL, check=False)

        # 10. 取得
        state_dir.mkdir(parents=True, exist_ok=True)
        rep_local = state_dir / f"tmp_report_{run_id}.json"
        r = subprocess.run(scp_down(host, f"{REMOTE_BASE}/out/report_{run_id}.json", rep_local),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if r.returncode != 0 or not rep_local.exists():
            print("[book2md] 遠隔の実行が途中で終わりました。同じコマンドで続きから再開できます",
                  file=sys.stderr)
            return EXIT_REMOTE_INCOMPLETE
        remote_report = read_json(rep_local, {}) or {}
        os.replace(rep_local, state_dir / "remote_report.json")
        by_id = {b.get("job_id"): b for b in remote_report.get("books", [])}
        for pdf, jid in todo:
            results.append(_collect_book(host, pdf, jid, by_id.get(jid), folder, state_dir,
                                         check_only=getattr(args, "check_only", False)))

    # 11. まとめ
    books = results + [_skip_book(p, j, STATUS_SKIPPED_DONE, state, folder) for p, j in done] \
        + [_skip_book(p, "", STATUS_SKIPPED_PGX, state, folder) for p in skipped_pgx]
    report = build_report(books, started=started, finished=_now())
    atomic_write_json(state_dir / "report.json", report)
    text = render_text(report)
    atomic_write_text(state_dir / "report.txt", text)
    print(text, flush=True)
    for b in results:
        state[b["job_id"]] = {"name": b["name"], "status": b["status"],
                              "pages": b.get("pages"), "updated": _now()}
    atomic_write_json(state_path, state)

    # 12. 終了コード
    return 1 if any(b.get("status") == STATUS_FAILED for b in books) else 0


def _collect_book(host: str, pdf: Path, jid: str, rb: dict | None, folder: Path, state_dir: Path,
                  check_only: bool = False) -> dict:
    """遠隔の 1 冊分の結果を Air 側に取り込み、Air のパスに書き換えた dict を返す。"""
    if rb is None:
        rb = {"job_id": jid, "pages": None, "status": STATUS_FAILED,
              "error": "遠隔のレポートにこの本がありません", "check": None, "ocr": None,
              "elapsed_sec": None, "renamed_to": None}
    book = dict(rb)
    book.update({"job_id": jid, "name": pdf.name, "source": str(pdf), "md": None})
    _int_keys(book.get("check"))
    status = book.get("status")
    try:
        if status in (STATUS_OK, STATUS_OK_UNCHECKED):
            tmp = state_dir / f"tmp_{jid}.md"
            _run(scp_down(host, f"{REMOTE_BASE}/out/{jid}.md", tmp), "MD の取得")
            dest = folder / f"{pdf.stem}.md"
            moved = backup_existing(dest, state_dir / "backup", tmp.read_bytes())
            if moved:
                _log(f"既存の MD を退避しました: {moved}")
            os.replace(tmp, dest)
            book["md"] = str(dest)
            _fetch_check(host, jid, pdf, state_dir)
        elif status in (STATUS_CHECKED_OK, STATUS_CHECKED_UNCERTAIN):
            _fetch_check(host, jid, pdf, state_dir)
        elif status == STATUS_MISSING and check_only:
            _fetch_check(host, jid, pdf, state_dir)
        elif status == STATUS_MISSING:
            _fetch_check(host, jid, pdf, state_dir)
            new = folder / pgx_name(pdf.name)
            if new.exists():
                book["status"] = STATUS_FAILED
                book["error"] = "リネーム先が既にある: " + new.name
            else:
                pdf.rename(new)
                book["renamed_to"] = str(new)
    except (RuntimeError, OSError) as e:
        book["status"] = STATUS_FAILED
        book["error"] = f"{type(e).__name__}: {e}"
    return book


def _fetch_check(host: str, jid: str, pdf: Path, state_dir: Path) -> None:
    """check.json を取得する。取れなくても本の結果は変えず、警告だけ出す。"""
    try:
        _run(scp_down(host, f"{REMOTE_BASE}/out/{jid}.check.json",
                      state_dir / f"{pdf.stem}.check.json"), "check.json の取得")
    except RuntimeError as e:
        _log(f"警告: {e}")
