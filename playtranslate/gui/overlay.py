"""Arabic text drawn over the PS Remote Play window on the laptop.

Used when the laptop itself is connected to the TV (fallback for TVs that
can't run the TV app). The window is transparent, always on top, ignores the
mouse, and hides itself from screen capture so the tool never reads its own
Arabic text back.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen, QTextCharFormat, QTextLayout, QTextOption,
)
from PySide6.QtWidgets import QWidget

from .. import winapi
from ..config import Style

log = logging.getLogger(__name__)


def physical_to_logical(x: int, y: int, w: int, h: int) -> QRect:
    """Window-API pixels -> Qt logical coordinates (handles display scaling)."""
    for screen in QGuiApplication.screens():
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        # On Windows, Qt keeps each screen's origin in physical pixels and scales its size.
        px0, py0 = geo.x(), geo.y()
        px1, py1 = px0 + geo.width() * dpr, py0 + geo.height() * dpr
        if px0 <= x < px1 and py0 <= y < py1:
            return QRect(int(px0 + (x - px0) / dpr), int(py0 + (y - py0) / dpr), int(w / dpr), int(h / dpr))
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    return QRect(int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr))


class OverlayWindow(QWidget):
    def __init__(self, style: Style):
        super().__init__(None)
        self.style_cfg = style
        self.lines: list[dict] = []
        self.capture_safe = False
        self._crop_top_ratio = 0.76  # where the subtitle region starts, as a fraction of height
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                 | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setLayoutDirection(Qt.RightToLeft)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            self.capture_safe = winapi.exclude_from_capture(int(self.winId()))
            if not self.capture_safe:
                log.info("Overlay cannot hide from capture (Windows older than 2004); drawing above the subtitle area")

    def follow(self, pic_left: int, pic_top: int, pic_width: int, pic_height: int, crop_top: int) -> None:
        rect = physical_to_logical(pic_left, pic_top, pic_width, pic_height)
        if rect != self.geometry():
            self.setGeometry(rect)
        self._crop_top_ratio = crop_top / max(1, pic_height)

    def set_style(self, style: Style) -> None:
        self.style_cfg = style
        self.update()

    def show_lines(self, lines: list[dict]) -> None:
        self.lines = lines
        if not self.isVisible():
            self.show()
        self.update()

    def clear(self) -> None:
        self.lines = []
        self.update()

    def _layout(self, text: str, font: QFont, width: float, speaker_len: int) -> tuple[QTextLayout, float]:
        option = QTextOption(Qt.AlignHCenter)
        option.setTextDirection(Qt.RightToLeft)
        option.setWrapMode(QTextOption.WordWrap)
        layout = QTextLayout(text, font)
        layout.setTextOption(option)
        if speaker_len:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.style_cfg.speaker_color))
            fmt.setFontWeight(QFont.Bold)
            rng = QTextLayout.FormatRange()
            rng.start, rng.length, rng.format = 0, speaker_len, fmt
            layout.setFormats([rng])
        spacing = QFontMetricsF(font).lineSpacing()
        layout.beginLayout()
        y = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, y))
            y += spacing
        layout.endLayout()
        return layout, y

    def paintEvent(self, event):
        if not self.lines:
            return
        s = self.style_cfg
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        font = QFont(s.font_family)
        font.setPixelSize(max(12, int(s.font_size * h / 1080)))
        font.setStyleStrategy(QFont.PreferAntialias)
        pad = font.pixelSize() * 0.35
        area_w = w * s.max_width
        inner_w = area_w - 2 * pad

        # Each line is laid out centred inside a column of width inner_w that is
        # itself centred on screen, so the text and its box share one centre.
        blocks = []
        total_h = 0.0
        text_w = 0.0
        for line in self.lines:
            speaker = line.get("speaker") or ""
            body = line.get("text", "")
            text = f"{speaker}: {body}" if speaker else body
            speaker_len = len(speaker) + 1 if speaker else 0
            colored, height = self._layout(text, font, inner_w, speaker_len)
            plain, _ = self._layout(text, font, inner_w, 0)
            for i in range(colored.lineCount()):
                text_w = max(text_w, colored.lineAt(i).naturalTextWidth())
            blocks.append((colored, plain, height))
            total_h += height
        box_w = min(area_w, text_w + 2 * pad)
        box_h = total_h + 2 * pad

        bottom = h * (1 - s.bottom_margin)
        if not self.capture_safe:
            # Keep clear of the area we read, or the OCR would see our own text.
            bottom = min(bottom, h * self._crop_top_ratio - 4)
        box = QRectF((w - box_w) / 2, bottom - box_h, box_w, box_h)

        if s.background_opacity > 0:
            bg = QColor(s.background_color)
            bg.setAlphaF(s.background_opacity)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(box, pad * 0.6, pad * 0.6)

        x0 = (w - area_w) / 2 + pad
        y = box.top() + pad
        for colored, plain, height in blocks:
            origin = QPointF(x0, y)
            if s.outline:
                # A dark ring around each glyph keeps text readable on any scene.
                p.setPen(QPen(QColor(0, 0, 0, 210)))
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                    plain.draw(p, origin + QPointF(dx, dy))
            p.setPen(QColor(s.text_color))
            colored.draw(p, origin)
            y += height
        p.end()
