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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="PlayTranslate")
    parser.add_argument("--video", help="recorded gameplay video to read instead of PS Remote Play")
    parser.add_argument("--images", help="folder of screenshots to read instead of PS Remote Play")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    log = logging.getLogger("playtranslate")
    log.info("PlayTranslate %s starting on %s (build %s)", __version__, sys.platform, winapi.windows_build())
    winapi.enable_dpi_awareness()

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
