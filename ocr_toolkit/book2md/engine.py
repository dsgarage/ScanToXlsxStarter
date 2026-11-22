"""PaddleOCR の生成と 1 枚の推論(結果を dict に正規化)。paddleocr は関数の中で import する。"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def detect_device(device_opt: str) -> str:
    """"auto" | "gpu" | "cpu" → "gpu:0" か "cpu"。"""
    if device_opt == "cpu":
        return "cpu"
    try:
        import paddle

        ok = bool(
            paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
        )
    except Exception:
        ok = False
    if ok:
        return "gpu:0"
    if device_opt == "gpu":
        raise RuntimeError("GPU が使えません")
    return "cpu"


def resolve_model(model_opt: str, device: str) -> str:
    """"auto" → gpu なら "server"、cpu なら "mobile"。"""
    if model_opt != "auto":
        return model_opt
    return "server" if device.startswith("gpu") else "mobile"


class OcrEngine:
    def __init__(self, *, model: str, device: str | None, textline_orientation: bool):
        from paddleocr import PaddleOCR

        self.info = {
            "model": f"PP-OCRv5_{model}",
            "device": device or "auto",
            "textline_orientation": bool(textline_orientation),
        }
        kwargs = dict(
            lang="japan",
            text_detection_model_name=f"PP-OCRv5_{model}_det",
            text_recognition_model_name=f"PP-OCRv5_{model}_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=textline_orientation,
        )
        if device:
            kwargs["device"] = device
        self._ocr = PaddleOCR(**kwargs)

    def run(self, image_path: str | Path) -> dict:
        from PIL import Image

        with Image.open(image_path) as im:
            w, h = im.size
        r = self._ocr.predict(str(image_path))[0]
        # rec_texts / rec_scores / rec_boxes は同じ並び(dt_polys は間引き前なので使わない)
        texts = [str(t) for t in r["rec_texts"]]
        scores = [float(s) for s in r["rec_scores"]]
        boxes = [[float(v) for v in b] for b in _tolist(r["rec_boxes"])]
        return {"w": w, "h": h, "texts": texts, "scores": scores, "boxes": boxes}


def _tolist(x):
    return x.tolist() if hasattr(x, "tolist") else list(x)
