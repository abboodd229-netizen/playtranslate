import asyncio
import json
import socket
import threading
import time

import aiohttp
import numpy as np
import pytest

from playtranslate.capture import FrameSource, _ArraySource
from playtranslate.config import Region
from playtranslate.pipeline import Pipeline, PipelineSettings
from playtranslate.server import DisplayServer
from playtranslate.textproc import similar
from playtranslate.translate.cache import TranslationCache
from playtranslate.translate.service import TranslationService

from synth import frame
from test_translate import FakeEngine


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_websocket_and_overlay_page():
    port, dport = free_port(), free_port()
    srv = DisplayServer(port=port, discovery_port=dport, name="test")
    assert srv.start()
    srv.set_style({"font_size": 50})
    srv.show([{"speaker": "", "text": "قبل الاتصال"}])

    async def client():
        async with aiohttp.ClientSession() as s:
            async with s.get(f"http://127.0.0.1:{port}/overlay") as r:
                assert r.status == 200 and "PlayTranslate" in await r.text()
            async with s.ws_connect(f"http://127.0.0.1:{port}/ws") as ws:
                hello = await ws.receive_json(timeout=3)
                assert hello["type"] == "hello" and hello["style"]["font_size"] == 50
                replay = await ws.receive_json(timeout=3)
                assert replay["type"] == "show" and replay["lines"][0]["text"] == "قبل الاتصال"
                await ws.send_json({"type": "hello", "client": "tv", "name": "Living room"})
                await asyncio.sleep(0.2)
                assert srv.clients[0]["client"] == "tv"
                srv.show([{"speaker": "آرثر", "text": "مرحبا"}])
                msg = await ws.receive_json(timeout=3)
                assert msg["type"] == "show" and msg["lines"][0]["speaker"] == "آرثر"
                srv.hide()
                msg = await ws.receive_json(timeout=3)
                assert msg["type"] == "hide"

    try:
        asyncio.run(client())
    finally:
        srv.stop()


def test_beacon_is_broadcast():
    port, dport = free_port(), free_port()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    rx.bind(("", dport))
    rx.settimeout(4)
    srv = DisplayServer(port=port, discovery_port=dport)
    srv.start()
    try:
        data, _addr = rx.recvfrom(4096)
        msg = json.loads(data)
        assert msg["app"] == "playtranslate" and msg["port"] == port
    finally:
        srv.stop()
        rx.close()


def test_port_in_use_reports_error():
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        s.listen()
        port = s.getsockname()[1]
        srv = DisplayServer(port=port, discovery_port=free_port())
        assert not srv.start()
        assert "مستخدم" in srv.start_error
        srv.stop()


class ScriptSource(_ArraySource):
    """Plays a list of (frame, seconds) like a game would."""

    def __init__(self, script, region):
        super().__init__(region)
        self.script = script
        self.start = time.monotonic()

    def _next_full(self):
        t = time.monotonic() - self.start
        for img, dur in self.script:
            if t < dur:
                return img
            t -= dur
        return None


class RecordingSink:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def show(self, lines):
        with self.lock:
            self.events.append(("show", lines, time.monotonic()))

    def hide(self):
        with self.lock:
            self.events.append(("hide", None, time.monotonic()))


def test_pipeline_end_to_end(rapid_engine):
    blank = frame(None, seed=1)
    a = frame("ARTHUR: We need to leave town before dawn.", seed=1)
    b = frame("Get the horses ready.", seed=1)
    script = [(blank, 0.4), (a, 1.6), (blank, 1.2), (b, 1.6), (blank, 1.2)]
    engine = FakeEngine()
    svc = TranslationService(TranslationCache(":memory:"), [engine], "g", {"Arthur": "آرثر"})
    sink = RecordingSink()
    stopped = threading.Event()
    p = Pipeline(lambda: ScriptSource(script, Region()), svc, [sink],
                 PipelineSettings(fps=10, linger_ms=300), ocr_engine=rapid_engine)
    subtitles = []
    p.on_subtitle = subtitles.append
    p.on_stopped = lambda reason: stopped.set()
    p.start()
    assert stopped.wait(15)
    p.shutdown()

    kinds = [e[0] for e in sink.events]
    assert kinds == ["show", "hide", "show", "hide"], sink.events
    first = sink.events[0][1][0]
    assert first["speaker"] == "آرثر"
    assert similar(first["text"], "AR[We need to leave town before dawn.]", 0.9)
    assert similar(sink.events[2][1][0]["text"], "AR[Get the horses ready.]", 0.9)
    # Shown well within a second of the subtitle appearing (fake translator, real OCR).
    for ev in subtitles:
        assert ev.total_ms < 1000, ev
        print(f"OCR {ev.ocr_ms:.0f} ms, total {ev.total_ms:.0f} ms")
