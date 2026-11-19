"""Text recognition engines.

`create_engine("auto")` returns Windows OCR when it is available with English
installed, otherwise RapidOCR (works on every Windows version, offline).
"""

from __future__ import annotations

import logging

from .base import OcrEngine, OcrLine, OcrUnavailable

log = logging.getLogger(__name__)

__all__ = ["OcrEngine", "OcrLine", "OcrUnavailable", "create_engine"]


def create_engine(name: str = "auto") -> OcrEngine:
    errors: list[str] = []
    order = {"auto": ["windows", "rapid"], "windows": ["windows"], "rapid": ["rapid"]}.get(name, ["windows", "rapid"])
    for candidate in order:
        try:
            if candidate == "windows":
                from .windows_ocr import WindowsOcr

                engine: OcrEngine = WindowsOcr()
            else:
                from .rapid import RapidOcr

                engine = RapidOcr()
            log.info("OCR engine: %s", engine.name)
            return engine
        except OcrUnavailable as exc:
            log.info("OCR engine %s unavailable: %s", candidate, exc)
            errors.append(f"{candidate}: {exc}")
    raise OcrUnavailable("؛ ".join(errors))
