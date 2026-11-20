"""RapidOCR (PaddleOCR models on ONNX Runtime): offline, any Windows version."""

from __future__ import annotations

import logging
import threading

import numpy as np

from .base import OcrEngine, OcrLine, OcrUnavailable, prepare, sort_lines

log = logging.getLogger(__name__)


class RapidOcr(OcrEngine):
    name = "RapidOCR"

    def __init__(self, min_score: float = 0.5):
        try:
            from rapidocr import RapidOCR
        except Exception as exc:  # ImportError or a broken onnxruntime DLL
            raise OcrUnavailable(f"RapidOCR غير مثبت ({exc})") from exc
        try:
            self._engine = RapidOCR(params={
                "Global.use_cls": False,  # subtitles are never upside down
                "Global.log_level": "warning",
                "Global.text_score": min_score,
            })
        except Exception as exc:
            raise OcrUnavailable(f"تعذّر تشغيل RapidOCR ({exc})") from exc
        self.min_score = min_score
        # ONNX sessions are thread-safe, but serialising keeps CPU use predictable.
        self._lock = threading.Lock()

    def recognize(self, image: np.ndarray, rows=None) -> list[OcrLine]:
        if rows:
            lines = self._read_rows(image, rows)
            if lines:
                return lines
        return self._detect_and_read(image)

    def _read_rows(self, image: np.ndarray, rows) -> list[OcrLine]:
        """Recognition only, one call per line: ~10 ms a line instead of ~1 s for detection."""
        lines: list[OcrLine] = []
        for x, y, w, h in rows:
            piece = image[y:y + h, x:x + w]
            if piece.size == 0 or h < 6:
                continue
            piece, _ = prepare(piece, min_height=40, max_height=96)
            with self._lock:
                result = self._engine(piece, use_det=False, use_cls=False)
            txts = getattr(result, "txts", None) or ()
            scores = getattr(result, "scores", None) or ()
            for text, score in zip(txts, scores):
                if text and float(score) >= self.min_score:
                    lines.append(OcrLine(str(text), (x, y, w, h), float(score)))
        return sort_lines(lines)

    def recognize_page(self, image: np.ndarray) -> list[OcrLine]:
        # Keep full resolution (up to 1080 lines) so small menu text stays readable.
        return self._detect_and_read(image, max_height=1080)

    def _detect_and_read(self, image: np.ndarray, max_height: int = 360) -> list[OcrLine]:
        img, scale = prepare(image, min_height=48, max_height=max_height)
        with self._lock:
            # Say so explicitly: RapidOCR remembers use_det=False from _read_rows
            # and would otherwise skip detection on every later call.
            result = self._engine(img, use_det=True, use_cls=False, use_rec=True)
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or txts is None:
            return []
        lines: list[OcrLine] = []
        for box, text, score in zip(boxes, txts, scores if scores is not None else [1.0] * len(txts)):
            if not text or float(score) < self.min_score:
                continue
            pts = np.asarray(box, dtype=np.float32)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            lines.append(OcrLine(
                str(text),
                (int(x0 / scale), int(y0 / scale), int((x1 - x0) / scale), int((y1 - y0) / scale)),
                float(score),
            ))
        return sort_lines(lines)
