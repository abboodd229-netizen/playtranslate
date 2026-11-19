"""Entry point: `python -m playtranslate` or the packaged PlayTranslate.exe.

Options for testing without a PS5:
    --video clip.mp4      read subtitles from a recorded gameplay video
    --images folder       read subtitles from screenshots (2 s each)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import traceback

from . import __version__, winapi
from .config import data_dir, load_config


def setup_logging(verbose: bool = False) -> None:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "playtranslate.log", maxBytes=2_000_000,
                                                   backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:  # windowed exe has no console
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)
    for noisy in ("aiohttp.access", "RapidOCR", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def selftest() -> int:
    """Checks OCR engines on a generated subtitle; prints and saves a report. Exit 0 if any engine works."""
    import time

    import cv2
    import numpy as np

    from .config import Region
    from .detect import Stable, SubtitleDetector
    from .ocr import OcrUnavailable
    from .textproc import joined, similar, to_segments

    expected = "We need to leave town before dawn."
    img = np.full((720, 1280, 3), 60, np.uint8)
    cv2.putText(img, expected, (230, 620), cv2.FONT_HERSHEY_DUPLEX, 1.3, (0, 0, 0), 7, cv2.LINE_AA)
    cv2.putText(img, expected, (230, 620), cv2.FONT_HERSHEY_DUPLEX, 1.3, (255, 255, 255), 2, cv2.LINE_AA)
    x, y, w, h = Region().to_pixels(1280, 720)
    det = SubtitleDetector()
    event = None
    for _ in range(3):
        event = det.feed(img[y:y + h, x:x + w]) or event
    report = [f"PlayTranslate {__version__} self-test, Windows build {winapi.windows_build()}"]
    ok = False
    if not isinstance(event, Stable):
        report.append("detector: FAILED (no subtitle found)")
    else:
        report.append(f"detector: ok, {len(event.rows)} line(s)")
        engines = []
        try:
            from .ocr.windows_ocr import WindowsOcr
            engines.append(WindowsOcr)
        except Exception as exc:  # import problems are reported below
            report.append(f"Windows OCR: import failed ({exc})")
        from .ocr.rapid import RapidOcr
        engines.append(RapidOcr)
        for cls in engines:
            try:
                engine = cls()
                engine.warm_up()
                t = time.perf_counter()
                text = joined(to_segments(engine.recognize(event.image, event.rows)))
                ms = (time.perf_counter() - t) * 1000
                good = similar(text, expected, 0.85)
                ok |= good
                report.append(f"{engine.name}: {'ok' if good else 'MISREAD'} in {ms:.0f} ms -> {text!r}")
            except OcrUnavailable as exc:
                report.append(f"{cls.__name__}: unavailable ({exc})")
            except Exception as exc:
                report.append(f"{cls.__name__}: ERROR {exc!r}")
    report.append("RESULT: PASS" if ok else "RESULT: FAIL")
    text = "\n".join(report)
    (data_dir() / "selftest.txt").write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="PlayTranslate")
    parser.add_argument("--video", help="recorded gameplay video to read instead of PS Remote Play")
    parser.add_argument("--images", help="folder of screenshots to read instead of PS Remote Play")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--selftest", action="store_true", help="check OCR engines and exit")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    log = logging.getLogger("playtranslate")
    log.info("PlayTranslate %s starting on %s (build %s)", __version__, sys.platform, winapi.windows_build())
    winapi.enable_dpi_awareness()
    if args.selftest:
        return selftest()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv[:1])
    app.setApplicationName("PlayTranslate")
    app.setLayoutDirection(Qt.RightToLeft)
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))

    def excepthook(exc_type, exc, tb):
        log.critical("Unhandled error", exc_info=(exc_type, exc, tb))
        text = "".join(traceback.format_exception_only(exc_type, exc)).strip()
        QMessageBox.critical(None, "خطأ", f"حدث خطأ غير متوقع:\n{text}\n\nالتفاصيل في ملف السجل:\n{data_dir() / 'logs'}")

    sys.excepthook = excepthook

    from .controller import Controller
    from .gui.main_window import MainWindow

    source = ("video", args.video) if args.video else ("images", args.images) if args.images else None
    controller = Controller(load_config(), source)
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
