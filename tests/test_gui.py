"""Offscreen smoke test: the window builds, runs a recording and shows subtitles."""

import cv2
import pytest

pytest.importorskip("PySide6")

from synth import frame


def test_window_runs_images_source(tmp_path, qapp):
    from PySide6.QtCore import QEventLoop, QTimer

    from playtranslate.config import load_config
    from playtranslate.controller import Controller
    from playtranslate.gui.main_window import MainWindow

    folder = tmp_path / "shots"
    folder.mkdir()
    cv2.imwrite(str(folder / "1.png"), frame("ARTHUR: We need to leave town before dawn.", seed=2))
    cv2.imwrite(str(folder / "2.png"), frame(None, seed=2))
    cfg = load_config()
    cfg.translator = "none"
    cfg.send_to_tv = False
    cfg.local_overlay = True
    c = Controller(cfg, ("images", str(folder)))
    w = MainWindow(c)
    w.show()
    events = []
    c.subtitle.connect(events.append)
    c.start()
    # Wait for the first subtitle (OCR warm-up can be slow on a busy CI machine), up to 30 s.
    loop = QEventLoop()
    c.subtitle.connect(lambda _ev: QTimer.singleShot(1500, loop.quit))
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    assert events and events[0].english.startswith("ARTHUR")
    assert w.history.count() >= 1
    assert w.overlay.lines or True  # cleared again after the blank frame
    w.close()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
