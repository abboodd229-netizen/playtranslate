"""Windows' built-in OCR (Windows.Media.Ocr), through the pywinrt packages.

Fast (tens of milliseconds) and free, but it needs the English OCR language
feature. Windows installed in Arabic may not have it; the app then falls back
to RapidOCR and the help page explains how to add English:

    Settings > Time & language > Language & region > Add a language > English (United States)

or, in an administrator PowerShell:

    Add-WindowsCapability -Online -Name "Language.OCR~~~en-US~0.0.1.0"
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading

import cv2
import numpy as np

from .base import OcrEngine, OcrLine, OcrUnavailable, prepare, sort_lines

log = logging.getLogger(__name__)

ENGLISH_TAGS = ("en-US", "en-GB", "en")


class WindowsOcr(OcrEngine):
    name = "Windows OCR"

    def __init__(self):
        if sys.platform != "win32":
            raise OcrUnavailable("Windows OCR يعمل على ويندوز فقط")
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine as WinOcrEngine
            from winrt.windows.storage.streams import DataWriter
        except Exception as exc:
            raise OcrUnavailable(f"مكتبات Windows OCR غير مثبتة ({exc})") from exc

        self._SoftwareBitmap = SoftwareBitmap
        self._BitmapPixelFormat = BitmapPixelFormat
        self._BitmapAlphaMode = BitmapAlphaMode
        self._DataWriter = DataWriter

        engine = None
        for tag in ENGLISH_TAGS:
            try:
                lang = Language(tag)
                if WinOcrEngine.is_language_supported(lang):
                    engine = WinOcrEngine.try_create_from_language(lang)
                    if engine is not None:
                        break
            except Exception:
                log.debug("OCR language %s failed", tag, exc_info=True)
        if engine is None:
            raise OcrUnavailable("لغة OCR الإنجليزية غير مثبتة في ويندوز")
        self._engine = engine
        self._max_dim = int(getattr(WinOcrEngine, "max_image_dimension", 4096) or 4096)
        # WinRT async calls need an event loop; keep one private loop per engine.
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()

    def _to_bitmap(self, bgr: np.ndarray):
        bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
        h, w = bgra.shape[:2]
        data = bgra.tobytes()
        writer = self._DataWriter()
        try:
            writer.write_bytes(data)
        except TypeError:
            # Older projections want a sequence of ints.
            writer.write_bytes(list(data))
        buffer = writer.detach_buffer()
        return self._SoftwareBitmap.create_copy_from_buffer(
            buffer, self._BitmapPixelFormat.BGRA8, w, h, self._BitmapAlphaMode.PREMULTIPLIED
        )

    def recognize(self, image: np.ndarray, rows=None) -> list[OcrLine]:
        # Windows OCR finds lines itself in a few milliseconds; rows are not needed.
        img, scale = prepare(image, min_height=60, max_height=min(600, self._max_dim))
        if img.shape[1] > self._max_dim:
            f = self._max_dim / img.shape[1]
            img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            scale *= f
        with self._lock:
            bitmap = self._to_bitmap(img)
            result = self._loop.run_until_complete(self._recognize(bitmap))
        lines: list[OcrLine] = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            xs, ys, x2, y2 = [], [], [], []
            for word in words:
                r = word.bounding_rect
                xs.append(r.x)
                ys.append(r.y)
                x2.append(r.x + r.width)
                y2.append(r.y + r.height)
            x0, y0 = min(xs), min(ys)
            lines.append(OcrLine(
                line.text,
                (int(x0 / scale), int(y0 / scale), int((max(x2) - x0) / scale), int((max(y2) - y0) / scale)),
                1.0,
            ))
        return sort_lines(lines)

    async def _recognize(self, bitmap):
        return await self._engine.recognize_async(bitmap)

    def __del__(self):
        loop = getattr(self, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.close()
