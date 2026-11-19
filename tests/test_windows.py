"""Windows-only checks; skipped elsewhere."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_windows_ocr_reads_subtitle():
    from playtranslate.config import Region
    from playtranslate.detect import Stable, SubtitleDetector
    from playtranslate.ocr import OcrUnavailable
    from playtranslate.textproc import joined, similar, to_segments

    from synth import frame

    try:
        from playtranslate.ocr.windows_ocr import WindowsOcr

        engine = WindowsOcr()
    except OcrUnavailable as exc:
        pytest.skip(f"Windows OCR not installed here: {exc}")
    img = frame("We need to leave town before dawn.", seed=3)
    x, y, w, h = Region().to_pixels(img.shape[1], img.shape[0])
    det = SubtitleDetector()
    ev = None
    for _ in range(3):
        ev = det.feed(img[y:y + h, x:x + w]) or ev
    assert isinstance(ev, Stable)
    text = joined(to_segments(engine.recognize(ev.image, ev.rows)))
    assert similar(text, "We need to leave town before dawn.", 0.85), text


def test_window_helpers_and_dpapi():
    from playtranslate import keystore, winapi

    winapi.enable_dpi_awareness()
    windows = winapi.list_windows()
    assert isinstance(windows, list)
    assert winapi.windows_build() >= 10240
    stored = keystore.protect("abc:fx")
    assert stored.startswith("dpapi:")
    assert keystore.unprotect(stored) == "abc:fx"
