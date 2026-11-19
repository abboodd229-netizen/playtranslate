"""Where frames come from.

* WindowCapture: the PS Remote Play window on Windows (the real thing).
* VideoFileSource / ImageFolderSource: recorded gameplay for testing and tuning
  without a PS5.

Every source returns a Frame holding only the subtitle crop plus the geometry
needed to place an overlay, so the rest of the pipeline never cares where the
pixels came from.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import winapi
from .config import Region

log = logging.getLogger(__name__)


@dataclass
class Frame:
    crop: np.ndarray  # BGR uint8, the subtitle region only
    # Picture (window client area) geometry, physical screen pixels.
    pic_left: int
    pic_top: int
    pic_width: int
    pic_height: int
    # Crop position inside the picture.
    crop_left: int
    crop_top: int
    timestamp: float


class CaptureError(Exception):
    """Raised with a user-facing (Arabic) message when capture cannot proceed."""


class FrameSource:
    region: Region

    def grab(self) -> Frame:
        raise NotImplementedError

    def grab_full(self) -> np.ndarray:
        """The whole picture, used by the region picker."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class WindowCapture(FrameSource):
    """Grabs the subtitle region of a window from the screen with mss.

    The window must be visible on screen (not minimized). Other windows may
    not cover it, because mss copies screen pixels. Our own overlay hides
    itself from capture (see winapi.exclude_from_capture).
    """

    def __init__(self, title_part: str, region: Region):
        self.title_part = title_part
        self.region = region
        self._hwnd: int | None = None
        self._last_lookup = 0.0
        # mss keeps per-thread GDI handles on Windows, so one instance per thread.
        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = mss.mss()
            self._local.sct = sct
        return sct

    def _window(self) -> winapi.WindowInfo:
        if not winapi.IS_WINDOWS:
            raise CaptureError("التقاط النافذة يعمل على ويندوز فقط")
        info = winapi.refresh_window(self._hwnd) if self._hwnd else None
        if info is None or self.title_part.lower() not in info.title.lower():
            now = time.monotonic()
            # Searching all windows is cheap but not free; at most twice a second.
            if now - self._last_lookup < 0.5 and self._hwnd is None:
                raise CaptureError(f"لم أجد نافذة «{self.title_part}». شغّل PS Remote Play")
            self._last_lookup = now
            info = winapi.find_window(self.title_part)
            self._hwnd = info.hwnd if info else None
        if info is None:
            raise CaptureError(f"لم أجد نافذة «{self.title_part}». شغّل PS Remote Play")
        if info.minimized:
            raise CaptureError("نافذة PS Remote Play مصغّرة. أرجعها للشاشة (لا تصغّرها)")
        if info.width < 320 or info.height < 180:
            raise CaptureError("نافذة PS Remote Play صغيرة جدًا. كبّرها لـ 1280×720 أو أكثر")
        return info

    def _grab_rect(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        shot = self._sct().grab({"left": left, "top": top, "width": width, "height": height})
        # mss gives BGRA; drop alpha and copy into a contiguous array.
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def grab(self) -> Frame:
        info = self._window()
        cl, ct, cw, ch = self.region.to_pixels(info.width, info.height)
        crop = self._grab_rect(info.left + cl, info.top + ct, cw, ch)
        return Frame(crop, info.left, info.top, info.width, info.height, cl, ct, time.monotonic())

    def grab_full(self) -> np.ndarray:
        info = self._window()
        return self._grab_rect(info.left, info.top, info.width, info.height)

    @property
    def hwnd(self) -> int | None:
        return self._hwnd


class _ArraySource(FrameSource):
    """Shared cropping for sources that produce whole pictures."""

    def __init__(self, region: Region):
        self.region = region
        self._last_full: np.ndarray | None = None

    def _next_full(self) -> np.ndarray | None:
        raise NotImplementedError

    def grab(self) -> Frame:
        full = self._next_full()
        if full is None:
            raise EOFError("end of recording")
        self._last_full = full
        h, w = full.shape[:2]
        cl, ct, cw, ch = self.region.to_pixels(w, h)
        crop = np.ascontiguousarray(full[ct:ct + ch, cl:cl + cw])
        return Frame(crop, 0, 0, w, h, cl, ct, time.monotonic())

    def grab_full(self) -> np.ndarray:
        if self._last_full is None:
            full = self._next_full()
            if full is None:
                raise CaptureError("لا توجد صور")
            self._last_full = full
        return self._last_full.copy()


class VideoFileSource(_ArraySource):
    """Plays a recorded clip at its own speed (or as fast as asked)."""

    def __init__(self, path: str | Path, region: Region, loop: bool = False):
        super().__init__(region)
        import cv2

        self._cv2 = cv2
        self.path = str(path)
        self.loop = loop
        self._cap = cv2.VideoCapture(self.path)
        if not self._cap.isOpened():
            raise CaptureError(f"لا يمكن فتح الفيديو: {self.path}")
        self.fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._start = time.monotonic()

    def _next_full(self) -> np.ndarray | None:
        # Seek to the frame matching wall-clock time so detection timing is realistic.
        target = int((time.monotonic() - self._start) * self.fps)
        current = int(self._cap.get(self._cv2.CAP_PROP_POS_FRAMES))
        if target > current + 1:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = self._cap.read()
        if not ok:
            if not self.loop:
                return None
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            self._start = time.monotonic()
            ok, frame = self._cap.read()
            if not ok:
                return None
        return frame

    def close(self) -> None:
        self._cap.release()


class ImageFolderSource(_ArraySource):
    """Shows each image for `seconds_each` seconds, in name order."""

    EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

    def __init__(self, folder: str | Path, region: Region, seconds_each: float = 2.0, loop: bool = False):
        super().__init__(region)
        import cv2

        self._cv2 = cv2
        self.files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in self.EXTS)
        if not self.files:
            raise CaptureError(f"لا توجد صور في {folder}")
        self.seconds_each = seconds_each
        self.loop = loop
        self._start = time.monotonic()
        self._cache: dict[int, np.ndarray] = {}

    def _next_full(self) -> np.ndarray | None:
        idx = int((time.monotonic() - self._start) / self.seconds_each)
        if idx >= len(self.files):
            if not self.loop:
                return None
            idx %= len(self.files)
        if idx not in self._cache:
            img = self._cv2.imdecode(np.fromfile(str(self.files[idx]), dtype=np.uint8), self._cv2.IMREAD_COLOR)
            if img is None:
                raise CaptureError(f"صورة تالفة: {self.files[idx]}")
            self._cache = {idx: img}
        return self._cache[idx]
