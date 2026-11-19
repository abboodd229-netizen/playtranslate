"""Dialog to draw the subtitle area on a screenshot of the game."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from ..config import Region


def bgr_to_qimage(img: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class _Canvas(QWidget):
    changed = Signal()

    def __init__(self, pixmap: QPixmap, region: Region):
        super().__init__()
        self.pixmap = pixmap
        self.setFixedSize(pixmap.size())
        w, h = pixmap.width(), pixmap.height()
        self.rect_px = QRect(int(region.x * w), int(region.y * h), int(region.w * w), int(region.h * h))
        self._origin: QPoint | None = None
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self.rect_px = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self.rect_px = QRect(self._origin, e.position().toPoint()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._origin is not None:
            self._origin = None
            self.changed.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pixmap)
        shade = QColor(0, 0, 0, 120)
        r = self.rect_px
        # Darken everything outside the chosen area.
        p.fillRect(QRect(0, 0, self.width(), r.top()), shade)
        p.fillRect(QRect(0, r.bottom() + 1, self.width(), self.height() - r.bottom() - 1), shade)
        p.fillRect(QRect(0, r.top(), r.left(), r.height()), shade)
        p.fillRect(QRect(r.right() + 1, r.top(), self.width() - r.right() - 1, r.height()), shade)
        p.setPen(QPen(QColor("#4fc3f7"), 2))
        p.drawRect(r)
        p.end()


class RegionPicker(QDialog):
    def __init__(self, frame_bgr: np.ndarray, region: Region, parent=None):
        super().__init__(parent)
        self.setWindowTitle("حدّد منطقة الحوار")
        self.setLayoutDirection(Qt.RightToLeft)
        image = bgr_to_qimage(frame_bgr)
        pix = QPixmap.fromImage(image)
        screen = self.screen().availableGeometry() if self.screen() else QRect(0, 0, 1280, 800)
        max_w, max_h = int(screen.width() * 0.85), int(screen.height() * 0.75)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.canvas = _Canvas(pix, region)

        hint = QLabel("اسحب بالماوس مستطيلًا حول مكان ظهور الترجمة الإنجليزية في اللعبة.\n"
                      "خلّه أعرض من أطول جملة، ويشمل سطرين أو ثلاثة، وما يشمل أشياء ثانية من الشاشة.")
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("حفظ")
        buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.canvas, alignment=Qt.AlignCenter)
        layout.addWidget(buttons)

    def region(self) -> Region:
        r = self.canvas.rect_px
        w, h = self.canvas.width(), self.canvas.height()
        region = Region(r.x() / w, r.y() / h, max(1, r.width()) / w, max(1, r.height()) / h)
        region.normalize()
        return region
