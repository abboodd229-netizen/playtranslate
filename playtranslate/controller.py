"""Glue between settings, the pipeline, the translator and the display server.

Lives in the GUI thread. Worker callbacks are turned into Qt signals, which
Qt delivers to the GUI thread safely.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .capture import CaptureError, FrameSource, ImageFolderSource, VideoFileSource, WindowCapture
from .config import AppConfig, data_dir, save_config
from .detect import DetectorSettings
from .ocr import OcrEngine
from .pipeline import Pipeline, PipelineSettings
from .server import DisplayServer, local_ips
from .translate import TranslationService
from .translate.base import EchoTranslator, TranslationError, Translator
from .translate.cache import TranslationCache

log = logging.getLogger(__name__)


class QtSink(QObject):
    """A pipeline sink that forwards to the GUI thread (for the laptop overlay)."""

    shown = Signal(list)
    hidden = Signal()

    def show(self, lines: list[dict]) -> None:
        self.shown.emit(lines)

    def hide(self) -> None:
        self.hidden.emit()


class Controller(QObject):
    status = Signal(str, str)  # text, level: info|ok|warn|error
    subtitle = Signal(object)  # SubtitleEvent
    hidden = Signal()
    geometry = Signal(object)  # capture.Frame
    clients_changed = Signal(list)
    running_changed = Signal(bool)
    engines_message = Signal(str, str)

    def __init__(self, cfg: AppConfig, source_spec: tuple[str, str] | None = None):
        super().__init__()
        self.cfg = cfg
        self.source_spec = source_spec
        self.cache = TranslationCache(data_dir() / "cache.sqlite3")
        self.server = DisplayServer(cfg.server_port, cfg.discovery_port)
        self.server.on_clients_changed = self.clients_changed.emit
        self.overlay_sink = QtSink()
        self.service = TranslationService(self.cache, self._build_engines(), cfg.active_profile,
                                          cfg.profile.glossary, cfg.use_context)
        self.pipeline: Pipeline | None = None
        self._ocr: OcrEngine | None = None
        self.ocr_name = ""

    # ---- engines -----------------------------------------------------

    def _build_engines(self) -> list[Translator]:
        engines: list[Translator] = []
        problems: list[str] = []
        choice = self.cfg.translator
        if choice == "deepl":
            try:
                from .translate.deepl import DeepLTranslator

                engines.append(DeepLTranslator(self.cfg.deepl_api_key))
            except TranslationError as exc:
                problems.append(str(exc))
        if choice in ("deepl", "argos"):
            # Argos is the offline fallback when DeepL is down or out of quota.
            from .translate import argos

            if argos.is_installed():
                try:
                    engines.append(argos.ArgosTranslator())
                except TranslationError as exc:
                    if choice == "argos":
                        problems.append(str(exc))
            elif choice == "argos":
                problems.append("مكتبة Argos غير مثبتة")
        if not engines:
            engines.append(EchoTranslator())
            if choice != "none":
                problems.append("سيظهر النص الإنجليزي بدون ترجمة")
        msg = "؛ ".join(problems)
        if msg:
            log.warning("Translation engines: %s", msg)
        self._engine_problem = msg
        return engines

    @property
    def engine_problem(self) -> str:
        return self._engine_problem

    # ---- server ------------------------------------------------------

    def start_server(self) -> None:
        if not self.cfg.send_to_tv:
            return
        if not self.server.running and not self.server.start():
            self.status.emit(f"تعذّر تشغيل خادم التلفزيون: {self.server.start_error}", "error")
            return
        self.server.set_style(asdict(self.cfg.style))

    def addresses(self) -> list[str]:
        return [f"{ip}:{self.cfg.server_port}" for ip in local_ips()]

    # ---- sources -----------------------------------------------------

    def make_source(self) -> FrameSource:
        region = self.cfg.profile.region
        if self.source_spec:
            kind, path = self.source_spec
            if kind == "video":
                return VideoFileSource(path, region, loop=True)
            return ImageFolderSource(path, region, loop=True)
        return WindowCapture(self.cfg.window_title, region)

    def grab_full_frame(self):
        """A whole picture for the region picker (GUI thread)."""
        src = self.make_source()
        try:
            return src.grab_full()
        finally:
            src.close()

    # ---- pipeline ----------------------------------------------------

    def pipeline_settings(self) -> PipelineSettings:
        p = self.cfg.profile
        return PipelineSettings(
            fps=self.cfg.capture_fps,
            linger_ms=self.cfg.linger_ms,
            split_speaker=p.split_speaker,
            detector=DetectorSettings(text_mode=p.text_mode, stroke_contrast=p.sensitivity),
        )

    def sinks(self) -> list:
        sinks = []
        if self.cfg.send_to_tv:
            sinks.append(self.server)
        if self.cfg.local_overlay:
            sinks.append(self.overlay_sink)
        return sinks

    def start(self) -> None:
        if self.pipeline and self.pipeline.running:
            return
        self.start_server()
        if self.engine_problem:
            self.status.emit(self.engine_problem, "warn")
        ocr_choice = self.cfg.ocr_engine
        if self._ocr is not None and self.ocr_name != ocr_choice:
            self._ocr = None
        p = Pipeline(self.make_source, self.service, self.sinks(), self.pipeline_settings(),
                     ocr_name=ocr_choice, ocr_engine=self._ocr)
        p.on_status = self.status.emit
        p.on_subtitle = self.subtitle.emit
        p.on_hide = self.hidden.emit
        p.on_geometry = self.geometry.emit
        p.on_stopped = self._on_stopped
        self.pipeline = p
        p.start()
        self.running_changed.emit(True)

    def _on_stopped(self, reason: str) -> None:
        p = self.pipeline
        if p is not None and p._ocr is not None:
            self._ocr = p._ocr  # keep the loaded models for the next start
            self.ocr_name = self.cfg.ocr_engine
        if reason:
            self.status.emit(reason, "warn" if "انتهى" in reason else "error")
        else:
            self.status.emit("متوقف", "info")
        self.running_changed.emit(False)

    def stop(self) -> None:
        if self.pipeline:
            self.pipeline.stop(wait=True)

    @property
    def running(self) -> bool:
        return bool(self.pipeline and self.pipeline.running)

    # ---- settings ----------------------------------------------------

    def apply(self, engines_changed: bool = False, glossary_changed: bool = False) -> None:
        """Push the current config to every part and save it."""
        cfg = self.cfg
        if glossary_changed:
            removed = self.cache.clear_machine(cfg.active_profile)
            log.info("Glossary changed; cleared %s cached lines", removed)
        self.service.set_profile(cfg.active_profile, cfg.profile.glossary)
        self.service.use_context = cfg.use_context
        if engines_changed:
            self.service.set_engines(self._build_engines())
            self.engines_message.emit(self.engine_problem, "warn" if self.engine_problem else "ok")
        if self.pipeline and self.pipeline.running:
            self.pipeline.update_settings(self.pipeline_settings())
            self.pipeline.sinks = self.sinks()
            if hasattr(self.pipeline.source, "region"):
                self.pipeline.source.region = cfg.profile.region
        if cfg.send_to_tv:
            self.start_server()
        self.server.set_style(asdict(cfg.style))
        self.save()

    def save(self) -> None:
        try:
            save_config(self.cfg)
        except OSError as exc:
            self.status.emit(f"تعذّر حفظ الإعدادات: {exc}", "error")

    def test_deepl(self, key: str, done) -> None:
        """Checks a key in the background; calls done(ok: bool, message: str) from that thread."""
        def run():
            from .translate.deepl import DeepLTranslator

            try:
                t = DeepLTranslator(key)
                used, limit = t.usage()
                sample = t.translate(["Hello, partner. Ready to ride?"])[0]
                t.close()
                left = max(0, limit - used)
                done(True, f"المفتاح يعمل ✓  المتبقي هذا الشهر: {left:,} حرف من {limit:,}\nمثال: {sample}")
            except TranslationError as exc:
                done(False, str(exc))
            except Exception as exc:
                done(False, f"خطأ: {exc}")

        threading.Thread(target=run, daemon=True).start()

    def send_test(self, text: str = "هذا نص تجربة. إذا شفته فالاتصال يعمل.") -> None:
        lines = [{"speaker": "PlayTranslate", "text": text}]
        self.start_server()
        if self.cfg.send_to_tv:
            self.server.show(lines)
        if self.cfg.local_overlay:
            self.overlay_sink.show(lines)

    def hide_test(self) -> None:
        self.server.hide()
        self.overlay_sink.hide()

    def shutdown(self) -> None:
        if self.pipeline:
            self.pipeline.shutdown()
        self.server.stop()
        self.service.set_engines([])
        self.cache.close()
