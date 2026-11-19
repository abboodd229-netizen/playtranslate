"""Decide when a subtitle has appeared, settled, changed or gone.

Running OCR on every frame would waste time and flicker. Instead each frame's
subtitle crop is reduced to a cheap "text mask" (thin bright strokes for light
subtitles, thin dark strokes for dark ones). The detector then emits:

* Stable: text is present and has not changed for `stable_frames` frames and
  differs from the last text we reported. Waiting for stability means
  typewriter-style subtitles are read once, complete.
* Gone: no text for `gone_frames` frames.

The Stable event also carries a tight crop around the text, which makes OCR
faster and stops it reading junk elsewhere in the region.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

SIG_W, SIG_H = 96, 24


@dataclass
class DetectorSettings:
    text_mode: str = "light"  # light | dark | auto
    # Fraction of crop pixels that must be text strokes to count as "text present".
    min_text_ratio: float = 0.0025
    # Minimum stroke contrast against the surroundings (0..255).
    stroke_contrast: int = 55
    stable_frames: int = 2
    gone_frames: int = 3
    # Signature difference (0..1) below which two frames count as the same text.
    same_threshold: float = 0.04
    # Difference from the last reported text needed to report again.
    new_threshold: float = 0.10


@dataclass
class Stable:
    image: np.ndarray  # tight BGR crop around the text
    bbox: tuple[int, int, int, int]  # x, y, w, h inside the region crop
    # Each text run (one line, or part of one) as x, y, w, h inside `image`.
    # Lets OCR skip its own slow text-finding step and just read the lines.
    rows: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class Gone:
    pass


def _stroke_kernel(height: int) -> np.ndarray:
    # Strokes are thinner than ~1/12 of a text line; the region is 1-3 lines tall.
    size = int(np.clip(height / 10, 9, 41)) | 1
    return cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))


def text_mask(crop: np.ndarray, mode: str, contrast: int) -> np.ndarray:
    """Binary mask (uint8 0/255) of thin text strokes in a BGR crop."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    kernel = _stroke_kernel(gray.shape[0])
    if mode == "dark":
        resp = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    elif mode == "auto":
        resp = np.maximum(
            cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel),
            cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel),
        )
    else:
        resp = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        # Subtitles are near-white or yellow; dim highlights are scenery.
        resp[gray < 150] = 0
    _, mask = cv2.threshold(resp, contrast, 255, cv2.THRESH_BINARY)
    # Remove isolated specks (noise, sparkles) but keep letters.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return mask


def _text_rows(comps: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
    """Group letter-sized blobs into horizontal runs of closely spaced pieces.

    Real subtitles are rows of several similar-height pieces with small gaps;
    scattered highlights in a scene are not.
    """
    if not comps:
        return []
    median_h = float(np.median([c[3] for c in comps]))
    remaining = sorted(comps, key=lambda c: c[1] + c[3] / 2)
    rows = []
    while remaining:
        centers = np.array([c[1] + c[3] / 2 for c in remaining])
        counts = [int(np.count_nonzero(np.abs(centers - cy) <= 0.6 * median_h)) for cy in centers]
        best = int(np.argmax(counts))
        cy = centers[best]
        row = [c for c, y in zip(remaining, centers) if abs(y - cy) <= 0.6 * median_h]
        remaining = [c for c, y in zip(remaining, centers) if abs(y - cy) > 0.6 * median_h]
        row.sort(key=lambda c: c[0])
        # Split the row where the horizontal gap is far wider than a word space.
        run = [row[0]]
        runs = []
        for c in row[1:]:
            prev = run[-1]
            if c[0] - (prev[0] + prev[2]) > 2.5 * median_h:
                runs.append(run)
                run = [c]
            else:
                run.append(c)
        runs.append(run)
        for run in runs:
            width = run[-1][0] + run[-1][2] - run[0][0]
            if len(run) >= 5 and width >= 4 * median_h:
                rows.append(run)
    return rows


Box = tuple[int, int, int, int]


def _looks_like_text(mask: np.ndarray, min_ratio: float) -> tuple[bool, Box | None, list[Box]]:
    ratio = float(np.count_nonzero(mask)) / mask.size
    if ratio < min_ratio or ratio > 0.35:
        return False, None, []
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    h_img = mask.shape[0]
    comps = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        # Letter-sized blobs: not a huge shape, not dust, not a long bar.
        if area < 6 or h > h_img * 0.8 or h < 5 or w > 4 * h + 10:
            continue
        comps.append((x, y, w, h))
    if len(comps) < 5:
        return False, None, []
    rows = _text_rows(comps)
    if not rows:
        return False, None, []
    row_boxes = []
    for row in rows:
        rx0 = min(c[0] for c in row)
        ry0 = min(c[1] for c in row)
        rx1 = max(c[0] + c[2] for c in row)
        ry1 = max(c[1] + c[3] for c in row)
        row_boxes.append((rx0, ry0, rx1 - rx0, ry1 - ry0))
    pieces = [c for row in rows for c in row]
    x0 = min(c[0] for c in pieces)
    y0 = min(c[1] for c in pieces)
    x1 = max(c[0] + c[2] for c in pieces)
    y1 = max(c[1] + c[3] for c in pieces)
    return True, (x0, y0, x1 - x0, y1 - y0), row_boxes


def signature(mask: np.ndarray) -> np.ndarray:
    small = cv2.resize(mask, (SIG_W, SIG_H), interpolation=cv2.INTER_AREA)
    return small > 40


def sig_diff(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """0 = identical text layout, 1 = completely different."""
    if a is None or b is None:
        return 1.0
    union = np.count_nonzero(a | b)
    if union == 0:
        return 0.0
    return float(np.count_nonzero(a ^ b)) / union


class SubtitleDetector:
    def __init__(self, settings: DetectorSettings | None = None):
        self.s = settings or DetectorSettings()
        self.reset()

    def reset(self) -> None:
        self._last_sig: np.ndarray | None = None
        self._reported_sig: np.ndarray | None = None
        self._stable = 0
        self._empty = 0
        self._showing = False

    def feed(self, crop: np.ndarray) -> Stable | Gone | None:
        mask = text_mask(crop, self.s.text_mode, self.s.stroke_contrast)
        present, bbox, row_boxes = _looks_like_text(mask, self.s.min_text_ratio)

        if not present:
            self._empty += 1
            self._stable = 0
            self._last_sig = None
            if self._showing and self._empty >= self.s.gone_frames:
                self._showing = False
                self._reported_sig = None
                return Gone()
            return None

        self._empty = 0
        sig = signature(mask)
        if sig_diff(sig, self._last_sig) <= self.s.same_threshold:
            self._stable += 1
        else:
            self._stable = 1
        self._last_sig = sig

        if self._stable < self.s.stable_frames:
            return None
        if self._reported_sig is not None and sig_diff(sig, self._reported_sig) < self.s.new_threshold:
            return None

        self._reported_sig = sig
        self._showing = True
        x, y, w, h = bbox
        pad = max(6, h // 3)
        H, W = crop.shape[:2]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        rows = []
        for rx, ry, rw, rh in sorted(row_boxes, key=lambda b: (b[1], b[0])):
            # Pad each line generously: outlines and descenders sit outside the strokes.
            rp = max(4, rh // 3)
            ax0, ay0 = max(x0, rx - rp), max(y0, ry - rp)
            ax1, ay1 = min(x1, rx + rw + rp), min(y1, ry + rh + rp)
            rows.append((ax0 - x0, ay0 - y0, ax1 - ax0, ay1 - ay0))
        return Stable(np.ascontiguousarray(crop[y0:y1, x0:x1]), (x0, y0, x1 - x0, y1 - y0), rows)
