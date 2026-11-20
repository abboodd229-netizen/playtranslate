"""Text recognition engines.

`create_engine("auto")` returns Windows OCR when it is available with English
installed, otherwise RapidOCR (works on every Windows version, offline).
"""

from __future__ import annotations

import logging
import re
import threading

from .base import OcrEngine, OcrLine, OcrUnavailable

log = logging.getLogger(__name__)

__all__ = ["OcrEngine", "OcrLine", "OcrUnavailable", "SecondOpinion", "create_engine", "garble_score"]


_ALLOWED = set("'\",.!?-:;…’‘“”()&/%$#+")
_MIXED_CASE = re.compile(r"[a-z][A-Z]")
_LETTER_DIGIT = re.compile(r"[A-Za-z]\d|\d[A-Za-z]")
_ORDINAL = re.compile(r"^\d+(st|nd|rd|th|s|am|pm|k|m)$", re.IGNORECASE)


def garble_score(text: str) -> float:
    """0 = reads like normal English, 1 = every word looks broken (OCR noise)."""
    words = text.split()
    if not words:
        return 1.0
    bad = 0
    for w in words:
        core = w.strip("'\",.!?:;…’‘“”()")
        if not core:
            continue
        if any(not (ch.isalnum() or ch in _ALLOWED) for ch in core):
            bad += 1
        elif _MIXED_CASE.search(core) and not core.isupper() and not core[:2] in ("Mc", "Ma"):
            bad += 1
        elif _LETTER_DIGIT.search(core) and not _ORDINAL.match(core):
            bad += 1
    return bad / len(words)


def _doubt(lines: list[OcrLine]) -> float:
    if not lines:
        return 1.0
    return max(garble_score(l.text) + max(0.0, 0.8 - l.confidence) for l in lines)


class SecondOpinion(OcrEngine):
    """Reads with the main engine; when a line looks broken, reads it again with the other one.

    The other engine loads in the background, so the first subtitles are never slowed
    down. Whichever reading looks cleaner is used. `on_doubt` sees every case where
    the main engine was unsure, which is how hard cases get collected for tuning.
    """

    DOUBT = 0.15

    def __init__(self, primary: OcrEngine, secondary_name: str):
        self.primary = primary
        self.name = primary.name
        self._secondary_name = secondary_name
        self._secondary: OcrEngine | None = None
        self._loading = False
        self._lock = threading.Lock()
        self.on_doubt = lambda image, first, second: None

    def _load_secondary(self) -> None:
        try:
            engine = create_engine(self._secondary_name, second_opinion=False)
            engine.warm_up()
            self._secondary = engine
        except OcrUnavailable as exc:
            log.info("No second OCR engine: %s", exc)

    def warm_up(self) -> None:
        self.primary.warm_up()
        with self._lock:
            if not self._loading:
                self._loading = True
                threading.Thread(target=self._load_secondary, name="ocr-second", daemon=True).start()

    def recognize(self, image, rows=None) -> list[OcrLine]:
        lines = self.primary.recognize(image, rows)
        doubt = _doubt(lines)
        if doubt < self.DOUBT:
            return lines
        other = self._secondary
        alt = other.recognize(image, rows) if other is not None else []
        try:
            self.on_doubt(image, lines, alt)
        except Exception:
            log.exception("on_doubt failed")
        if alt and _doubt(alt) < doubt:
            return alt
        return lines

    def recognize_page(self, image) -> list[OcrLine]:
        return self.primary.recognize_page(image)


def create_engine(name: str = "auto", second_opinion: bool = True) -> OcrEngine:
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
            if second_opinion:
                other = "rapid" if candidate == "windows" else "windows"
                return SecondOpinion(engine, other)
            return engine
        except OcrUnavailable as exc:
            log.info("OCR engine %s unavailable: %s", candidate, exc)
            errors.append(f"{candidate}: {exc}")
    raise OcrUnavailable("؛ ".join(errors))
