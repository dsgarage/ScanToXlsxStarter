"""PaddleOCR を ProcessPoolExecutor で並列実行するバッチランナー"""
from __future__ import annotations
import os
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Iterable

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_ocr = None  # ワーカープロセスごとの PaddleOCR インスタンス


def _init_worker(lang: str, use_mobile: bool) -> None:
    """ワーカー初期化時にPaddleOCRインスタンスを生成"""
    global _ocr
    from paddleocr import PaddleOCR

    kwargs = dict(
        lang=lang,
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )
    if use_mobile:
        kwargs.update(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
    _ocr = PaddleOCR(**kwargs)


def _run_one(img_path: str) -> tuple[str, str | None, str | None]:
    """1枚OCR。成功時(path, text, None)、失敗時(path, None, error)"""
    global _ocr
    try:
        result = _ocr.predict(img_path)
        texts = result[0]["rec_texts"]
        return img_path, "\n".join(texts), None
    except Exception as e:
        return img_path, None, str(e)


class BatchOCR:
    """画像ディレクトリを並列OCRしてテキストファイルに書き出す。

    使い方::

        from ocr_toolkit import BatchOCR
        runner = BatchOCR(lang="japan", workers=4, use_mobile=True)
        runner.run("crops/", "ocr/")

    主な特徴:
      - `PP-OCRv5_mobile` で高速化(`use_mobile=False` で server版)
      - 既存の `.txt` は自動スキップ(再開可能)
      - ProcessPoolExecutor で並列化
    """

    def __init__(
        self,
        *,
        lang: str = "japan",
        workers: int | None = None,
        use_mobile: bool = True,
    ) -> None:
        self.lang = lang
        self.workers = workers or max(1, min(6, (os.cpu_count() or 2)))
        self.use_mobile = use_mobile

    def run(
        self,
        src_dir: str | Path,
        out_dir: str | Path,
        *,
        glob_pattern: str = "*.png",
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """ディレクトリ配下の画像を並列OCR。

        Returns:
            {"done": N, "error": M, "skipped": K}
        """
        src = Path(src_dir)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        jobs = []
        skipped = 0
        for img in sorted(src.glob(glob_pattern)):
            txt = out / f"{img.stem}.txt"
            if skip_existing and txt.exists() and txt.stat().st_size > 0:
                skipped += 1
                continue
            jobs.append(str(img))

        if not jobs:
            return {"done": 0, "error": 0, "skipped": skipped}

        print(f"[ocr] {len(jobs)} jobs ({self.workers} workers, "
              f"mobile={self.use_mobile}, skipped={skipped})")

        start = time.time()
        done = err = 0
        with ProcessPoolExecutor(
            max_workers=self.workers,
            initializer=_init_worker,
            initargs=(self.lang, self.use_mobile),
        ) as ex:
            futures = {ex.submit(_run_one, j): j for j in jobs}
            for i, fut in enumerate(as_completed(futures), 1):
                img_path, text, e = fut.result()
                name = Path(img_path).stem
                if e:
                    err += 1
                    print(f"  [{i}/{len(jobs)}] {name}: ERROR {e}", flush=True)
                    continue
                (out / f"{name}.txt").write_text(text or "", encoding="utf-8")
                done += 1
                if i % 20 == 0:
                    el = time.time() - start
                    eta = el / i * (len(jobs) - i)
                    print(f"  [{i}/{len(jobs)}] {el:.0f}s elapsed, ETA {eta:.0f}s",
                          flush=True)

        print(f"[ocr] 完了 done={done} error={err} "
              f"({time.time() - start:.0f}s)")
        return {"done": done, "error": err, "skipped": skipped}
