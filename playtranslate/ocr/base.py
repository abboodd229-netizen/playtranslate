from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class OcrUnavailable(Exception):
    """The engine cannot run here; the message explains why (Arabic)."""


@dataclass
class OcrLine:
    text: str
    # Box inside the image given to the engine: x, y, w, h.
    box: tuple[int, int, int, int]
    confidence: float = 1.0


class OcrEngine:
    name = "base"

    def recognize(self, image: np.ndarray, rows: list[tuple[int, int, int, int]] | None = None) -> list[OcrLine]:
        """Lines of text in a BGR image, top to bottom.

        `rows` are line boxes already found by the detector; engines that can
        read a single line directly use them to skip text detection.
        """
        raise NotImplementedError

    def warm_up(self) -> None:
        """Load models now so the first subtitle is not slow."""
        blank = np.zeros((64, 256, 3), np.uint8)
        cv2.putText(blank, "Hello", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        try:
            self.recognize(blank)
            self.recognize(blank, [(0, 0, 256, 64)])
        except Exception:
            pass


def prepare(image: np.ndarray, min_height: int = 64, max_height: int = 400) -> tuple[np.ndarray, float]:
    """Scale small crops up (OCR misses tiny letters) and huge ones down.

    Returns the image and the scale factor applied.
    """
    h = image.shape[0]
    scale = 1.0
    if h < min_height:
        scale = min_height / h
    elif h > max_height:
        scale = max_height / h
    if scale != 1.0:
        interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=interp)
    return image, scale


def sort_lines(lines: list[OcrLine]) -> list[OcrLine]:
    """Top-to-bottom, then left-to-right, merging pieces on the same row."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (l.box[1] + l.box[3] / 2, l.box[0]))
    merged: list[OcrLine] = []
    for line in lines:
        if merged:
            prev = merged[-1]
            prev_mid = prev.box[1] + prev.box[3] / 2
            mid = line.box[1] + line.box[3] / 2
            if abs(mid - prev_mid) < 0.5 * max(prev.box[3], line.box[3]):
                first, second = (prev, line) if prev.box[0] <= line.box[0] else (line, prev)
                x0 = min(prev.box[0], line.box[0])
                y0 = min(prev.box[1], line.box[1])
                x1 = max(prev.box[0] + prev.box[2], line.box[0] + line.box[2])
                y1 = max(prev.box[1] + prev.box[3], line.box[1] + line.box[3])
                merged[-1] = OcrLine(
                    f"{first.text} {second.text}",
                    (x0, y0, x1 - x0, y1 - y0),
                    min(prev.confidence, line.confidence),
                )
                continue
        merged.append(line)
    return merged
