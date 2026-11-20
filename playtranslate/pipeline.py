"""The capture -> detect -> OCR -> translate -> display loop.

Runs in one worker thread at `capture_fps`. OCR happens in that thread
(tens of milliseconds on the subtitle crop). Translation runs in a second
thread so a slow network never stalls detection: if the subtitle changes or
disappears while a translation is in flight, the late result is cached but
not shown.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from .capture import CaptureError, Frame, FrameSource
from .detect import DetectorSettings, Gone, Stable, SubtitleDetector
from .ocr import OcrEngine, OcrUnavailable, create_engine
from .textproc import Segment, joined, page_segments, similar, to_segments
from .translate import TranslationResult, TranslationService
from .winapi import keep_awake

log = logging.getLogger(__name__)


class Sink(Protocol):
    # mode "subtitle" (normal) or "page" (a whole-screen translation: smaller text, centred).
    def show(self, lines: list[dict], mode: str = "subtitle") -> object: ...
    def hide(self) -> None: ...


@dataclass
class SubtitleEvent:
    english: str
    arabic: str
    segments: list[dict]
    origin: str
    ocr_ms: float
    translate_ms: float
    total_ms: float
    error: str = ""
    crop: np.ndarray | None = field(default=None, repr=False)
    # English text of each segment (without speaker), aligned with `segments`.
    sources: list[str] = field(default_factory=list)


@dataclass
class PipelineSettings:
    fps: int = 10
    linger_ms: int = 700
    split_speaker: bool = True
    # How long a whole-screen translation stays on the TV.
    page_seconds: float = 12.0
    detector: DetectorSettings = field(default_factory=DetectorSettings)


class Pipeline:
    def __init__(self, source_factory: Callable[[], FrameSource], translator: TranslationService,
                 sinks: list[Sink], settings: PipelineSettings, ocr_name: str = "auto",
                 ocr_engine: OcrEngine | None = None):
        self._source_factory = source_factory
        self.translator = translator
        self.sinks = list(sinks)
        self.settings = settings
        self._ocr_name = ocr_name
        self._ocr: OcrEngine | None = ocr_engine
        self._detector = SubtitleDetector(settings.detector)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._settings_lock = threading.Lock()
        self._pending_settings: PipelineSettings | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="translate")
        self._generation = 0
        # Guards generation/showing state shared by the worker and translate threads.
        self._display_lock = threading.RLock()
        self._shown_english = ""
        self._showing = False
        self._hide_at: float | None = None
        self._last_geometry: tuple | None = None
        self.source: FrameSource | None = None
        self._page_request = threading.Event()
        self._page_until: float | None = None

        # Callbacks (called from worker threads; GUI must marshal to its thread).
        self.on_status: Callable[[str, str], None] = lambda text, level: None
        self.on_subtitle: Callable[[SubtitleEvent], None] = lambda ev: None
        self.on_hide: Callable[[], None] = lambda: None
        self.on_geometry: Callable[[Frame], None] = lambda frame: None
        self.on_stopped: Callable[[str], None] = lambda reason: None
        # Called with "left" | "right" | "top" | "bottom" when subtitles keep touching that
        # edge of the region, i.e. they are probably cut off there.
        self.on_region_hint: Callable[[str], None] = lambda side: None
        self._edge_hits: dict[str, int] = {}
        # Called (OCR thread) with the image and both readings when the main OCR was unsure.
        self.on_doubt: Callable[[np.ndarray, list, list], None] = lambda image, first, second: None

    # ---- control -----------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    def shutdown(self) -> None:
        self.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def request_page(self) -> None:
        """Translate everything on screen once (menus, map, mission text).

        Asking again while it is shown hides it early. Thread-safe.
        """
        self._page_request.set()

    def update_settings(self, settings: PipelineSettings) -> None:
        """Applied by the worker at the start of its next frame."""
        with self._settings_lock:
            self._pending_settings = settings

    # ---- worker ------------------------------------------------------

    def _apply_pending(self) -> None:
        with self._settings_lock:
            pending, self._pending_settings = self._pending_settings, None
        if pending is not None:
            self.settings = pending
            self._detector = SubtitleDetector(pending.detector)

    def _run(self) -> None:
        reason = ""
        keep_awake(True)
        try:
            if self._ocr is None:
                self.on_status("جارٍ تحميل محرك القراءة…", "info")
                try:
                    self._ocr = create_engine(self._ocr_name)
                except OcrUnavailable as exc:
                    reason = f"لا يوجد محرك قراءة متاح: {exc}"
                    self.on_status(reason, "error")
                    return
                self._ocr.warm_up()
            if hasattr(self._ocr, "on_doubt"):
                self._ocr.on_doubt = lambda image, first, second: self.on_doubt(image, first, second)
            self.source = self._source_factory()
            self.on_status(f"يعمل ({self._ocr.name})", "ok")
            self._loop()
        except EOFError:
            reason = "انتهى التسجيل"
        except Exception as exc:  # last line of defence: report, don't vanish
            log.exception("Pipeline crashed")
            reason = f"خطأ غير متوقع: {exc}"
            self.on_status(reason, "error")
        finally:
            keep_awake(False)
            self._do_hide()
            if self.source is not None:
                try:
                    self.source.close()
                except Exception:
                    pass
            self.on_stopped(reason)

    def _loop(self) -> None:
        capture_problem = ""
        while not self._stop.is_set():
            self._apply_pending()
            interval = 1.0 / max(1, self.settings.fps)
            t0 = time.perf_counter()
            try:
                frame = self.source.grab()
            except CaptureError as exc:
                if str(exc) != capture_problem:
                    capture_problem = str(exc)
                    self.on_status(capture_problem, "warn")
                self._do_hide()
                self._stop.wait(0.5)
                continue
            if capture_problem:
                capture_problem = ""
                self.on_status(f"يعمل ({self._ocr.name})", "ok")

            geometry = (frame.pic_left, frame.pic_top, frame.pic_width, frame.pic_height, frame.crop_left, frame.crop_top)
            if geometry != self._last_geometry:
                self._last_geometry = geometry
                self.on_geometry(frame)

            if self._page_request.is_set():
                self._page_request.clear()
                if self._page_until is not None:
                    self._end_page()
                else:
                    self._do_page()
            if self._page_until is not None:
                # A whole-screen translation is up: subtitles wait until it ends.
                if time.monotonic() >= self._page_until:
                    self._end_page()
                self._stop.wait(max(0.0, interval - (time.perf_counter() - t0)))
                continue

            event = self._detector.feed(frame.crop)
            if isinstance(event, Stable):
                self._check_edges(event, frame.crop.shape)
                self._handle_stable(event, frame.timestamp)
            elif isinstance(event, Gone):
                with self._display_lock:
                    self._generation += 1  # drop translations still in flight
                    if self._showing:
                        self._hide_at = time.monotonic() + self.settings.linger_ms / 1000.0
            hide_at = self._hide_at
            if hide_at is not None and time.monotonic() >= hide_at:
                self._do_hide()

            elapsed = time.perf_counter() - t0
            self._stop.wait(max(0.0, interval - elapsed))

    def _check_edges(self, event: Stable, crop_shape: tuple[int, ...]) -> None:
        x, y, w, h = event.bbox
        H, W = crop_shape[:2]
        margin = 3
        touching = {
            "left": x <= margin, "right": x + w >= W - margin,
            "top": y <= margin, "bottom": y + h >= H - margin,
        }
        for side, hit in touching.items():
            if not hit:
                self._edge_hits[side] = 0
                continue
            self._edge_hits[side] = self._edge_hits.get(side, 0) + 1
            if self._edge_hits[side] >= 3:
                self._edge_hits[side] = 0
                self.on_region_hint(side)

    def _handle_stable(self, event: Stable, frame_ts: float) -> None:
        t_ocr = time.perf_counter()
        try:
            lines = self._ocr.recognize(event.image, event.rows)
        except Exception as exc:
            log.exception("OCR failed")
            self.on_status(f"تعذّرت القراءة: {exc}", "warn")
            return
        ocr_ms = (time.perf_counter() - t_ocr) * 1000
        segments = to_segments(lines, self.settings.split_speaker)
        if not segments:
            return
        english = joined(segments)
        with self._display_lock:
            if self._showing and similar(english, self._shown_english):
                # Same line re-read (lighting change, OCR jitter): keep what is on screen.
                self._hide_at = None
                return
            self._generation += 1
            generation = self._generation
            self._hide_at = None
        future: Future = self._executor.submit(self.translator.translate, segments)
        future.add_done_callback(
            lambda f: self._on_translated(f, generation, english, segments, ocr_ms, frame_ts, event.image)
        )

    def _on_translated(self, future: Future, generation: int, english: str, segments: list[Segment],
                       ocr_ms: float, frame_ts: float, crop: np.ndarray) -> None:
        try:
            result: TranslationResult = future.result()
        except Exception as exc:
            log.exception("Translation crashed")
            self.on_status(f"تعذّرت الترجمة: {exc}", "warn")
            return
        lines = [{"speaker": s.speaker_target, "text": s.target} for s in result.segments]
        with self._display_lock:
            if generation != self._generation or self._stop.is_set():
                return  # the subtitle changed or vanished meanwhile
            for sink in self.sinks:
                try:
                    sink.show(lines)
                except Exception:
                    log.exception("Sink %r failed", sink)
            self._showing = True
            self._shown_english = english
        total_ms = (time.monotonic() - frame_ts) * 1000
        if result.error:
            self.on_status(result.error, "warn")
        self.on_subtitle(SubtitleEvent(
            english=english, arabic=result.text, segments=lines, origin=result.origin,
            ocr_ms=ocr_ms, translate_ms=result.ms, total_ms=total_ms, error=result.error, crop=crop,
            sources=[s.source for s in result.segments],
        ))

    def _do_page(self) -> None:
        self.on_status("أقرأ الشاشة كاملة…", "info")
        t_ocr = time.perf_counter()
        try:
            full = self.source.grab_full()
            lines = self._ocr.recognize_page(full)
        except Exception as exc:
            log.exception("Page read failed")
            self.on_status(f"تعذّرت قراءة الشاشة: {exc}", "warn")
            return
        ocr_ms = (time.perf_counter() - t_ocr) * 1000
        segments = page_segments(lines)
        if not segments:
            self.on_status("ما لقيت نص إنجليزي على الشاشة.", "warn")
            return
        result: TranslationResult = self.translator.translate(segments)
        shown = [{"speaker": "", "text": s.target} for s in result.segments]
        with self._display_lock:
            self._generation += 1  # a subtitle still being translated must not replace the page
            for sink in self.sinks:
                try:
                    sink.show(shown, mode="page")
                except Exception:
                    log.exception("Sink %r failed", sink)
            self._showing = True
            self._shown_english = ""
            self._hide_at = None
        self._page_until = time.monotonic() + self.settings.page_seconds
        english = "\n".join(s.text for s in segments)
        self.on_status(f"ترجمة الشاشة معروضة لمدة {self.settings.page_seconds:.0f} ثانية.", "ok")
        if result.error:
            self.on_status(result.error, "warn")
        self.on_subtitle(SubtitleEvent(
            english=english, arabic=result.text, segments=shown, origin=result.origin,
            ocr_ms=ocr_ms, translate_ms=result.ms, total_ms=ocr_ms + result.ms, error=result.error,
            sources=[s.source for s in result.segments],
        ))

    def _end_page(self) -> None:
        self._page_until = None
        self._do_hide()
        # Report the subtitle that is on screen now, even if it was there before.
        self._detector.reset()
        self.on_status(f"يعمل ({self._ocr.name})", "ok")

    def _do_hide(self) -> None:
        with self._display_lock:
            self._hide_at = None
            if not self._showing:
                return
            self._showing = False
            self._shown_english = ""
            for sink in self.sinks:
                try:
                    sink.hide()
                except Exception:
                    log.exception("Sink %r failed", sink)
        self.on_hide()
